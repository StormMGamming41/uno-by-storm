"""
Networking for the UNO game. No pygame in here, so it also runs headless (see server.py).

Design:
- Plain TCP. Every message is one JSON object followed by a newline.
- Background threads only do the blocking work (accept / connect / recv) and push
  results into a queue. The game's main thread calls update() every frame, which drains
  that queue, so ALL state changes happen on the main thread (no locks needed elsewhere).
- The host plays through a normal Client connected to its own Server on 127.0.0.1,
  so the host and the guests share exactly the same code path.
- Players can also arrive through an "online room" (see relay.py): a mailbox on a public relay
  server instead of a TCP connection. Each way of arriving is a "link" with the same tiny
  interface (send / close / enable_compression), so everything below treats them alike.
- A "dedicated" Server has no local player: the first person to join becomes the lobby
  leader (and if they leave, the next person takes over). That is what server.py runs.

Made for the internet, where data is metered and connections are slow, drop silently, or get probed:
- Small on the wire: JSON without spaces, and after the welcome message everything the server
  sends is zlib-compressed as ONE continuous stream per connection (each message is flushed so
  it can be read immediately). Messages repeat almost everything from the one before, so the
  compressor makes them nearly free: a whole game goes from ~800 KB to a few dozen KB.
- Heartbeats: clients ping every few seconds; either side drops a peer that has been silent
  too long, so one dead connection can never freeze the game for everyone else.
- Sends have a timeout, so a stalled peer cannot block the server.
- Version check, optional lobby code, limits on connections / message rate / message size,
  and a cooldown after too many wrong codes.

Messages
  client -> server : {"type": "join", "v": <protocol version>, "token": <host token or None>,
                      "name": <username>, "code": <lobby code>}
                     {"type": "ping", "t": <number>}         sent every few seconds
                     {"type": "start"}                       leader only: start the game
                     {"type": "play", "card": <id>, "color": <color or None>}
                     {"type": "draw"}
                     {"type": "pass"}                        only after drawing a playable card
                     {"type": "to_lobby"}                    leader only: after a game is over
                     {"type": "resync"}                      "I may have missed something, send the state again"
  server -> client : {"type": "welcome", "id": <your id>}
                     {"type": "pong", "t": <the same number>}
                     {"type": "lobby", "players": [{"id", "name", "host", "points", "wins",
                                                    "games"}, ...]}   ("host" = lobby leader)
                     {"type": "state", "game": <what this player may see, see uno.UnoGame.view>}
                     {"type": "to_lobby"}                    the game is over, back to the lobby
                     {"type": "notice", "message": "..."}    a move was refused
                     {"type": "closed"}                      the lobby was closed
                     {"type": "error", "message": "..."}     e.g. lobby full, name taken, wrong code
"""

import hmac
import itertools
import json
import os
import queue
import re
import secrets
import socket
import threading
import time
import zlib

import relay
from uno import UnoGame

PROTOCOL_VERSION = 3     # bump when the messages change so mismatched copies refuse cleanly
DEFAULT_PORT = 5555
MAX_PLAYERS = 10
MIN_PLAYERS = 2          # needed to start a game
MAX_NAME = 12            # longest username
MAX_CODE = 32            # longest lobby code
HOST_NAME = "Host"       # the local host's name; guests can't take it
MAX_LINE = 64 * 1024     # a single message bigger than this is treated as abuse
MAX_INFLATED = 4 * MAX_LINE   # most data one received chunk may expand to (zip-bomb guard)

CONNECT_TIMEOUT = 5      # seconds to open the TCP connection
CONNECT_DEADLINE = 15    # seconds for the whole attempt (DNS, connecting, getting welcomed)
SEND_TIMEOUT = 3.0       # a send to a stuck peer gives up (and drops it) after this
HEARTBEAT_EVERY = 10.0   # clients ping this often (each ping+pong costs ~250 bytes on the wire)
IDLE_TIMEOUT = 30.0      # this long without hearing from the other side = connection is dead
JOIN_TIMEOUT = 10.0      # a connection must say who it is within this long
MAX_CONNECTIONS = 40
MAX_MSGS_PER_SEC = 40
BAD_CODE_LIMIT = 8       # this many wrong codes within BAD_CODE_WINDOW seconds...
BAD_CODE_WINDOW = 60     # ...and joining with a code is paused until it calms down


# ---------------------------------------------------------------- helpers

def get_local_ip() -> str:
    """The address other computers on your network can reach you at."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))  # UDP: nothing is actually sent
            return s.getsockname()[0]
    except OSError:
        pass
    try:
        return socket.gethostbyname(socket.gethostname())
    except OSError:
        return "127.0.0.1"


_HOST_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
                      r"(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$")


def parse_address(text: str, default_port: int = DEFAULT_PORT):
    """
    "192.168.0.10", "my-pc.example.com", "name.at.ply.gg:7261" or "tcp://0.tcp.ngrok.io:12345"
    -> (host, port). Raises ValueError with a message that is fine to show the player.
    """
    text = (text or "").strip()
    if "://" in text:
        text = text.split("://", 1)[1]
    text = text.rstrip("/")
    if not text:
        raise ValueError("Enter the server address.")

    host, port = text, default_port
    if ":" in text:
        host, _, port_text = text.rpartition(":")
        if not port_text.isdigit() or not 1 <= int(port_text) <= 65535:
            raise ValueError("The port after the colon must be a number from 1 to 65535.")
        port = int(port_text)
    if len(host) > 253 or not _HOST_RE.match(host):
        raise ValueError("That address doesn't look right.")
    return host, port


def clean_name(raw) -> str:
    """Trim, collapse repeated spaces, cut to MAX_NAME. Returns "" if nothing usable."""
    if not isinstance(raw, str):
        return ""
    name = " ".join(raw.split())[:MAX_NAME].strip()
    return name if name.isprintable() else ""


class Traffic:
    """Counts the bytes that actually cross the network (after compression), for the data meter."""

    def __init__(self):
        self.sent = 0
        self.received = 0
        self.sends = 0     # number of separate sends: each one is at least one network packet


def format_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.0f} KB" if n >= 10 * 1024 else f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def send_msg(sock: socket.socket, msg: dict, compressor=None) -> int:
    """Send one message (compact JSON + newline). Returns how many bytes went on the wire."""
    data = (json.dumps(msg, separators=(",", ":")) + "\n").encode("utf-8")
    if compressor is not None:
        # Z_SYNC_FLUSH makes this message decodable right away, while the compressor keeps its
        # memory of earlier messages (that memory is where the huge saving comes from).
        data = compressor.compress(data) + compressor.flush(zlib.Z_SYNC_FLUSH)
    sock.sendall(data)
    return len(data)


def _close_socket(sock: socket.socket):
    try:
        sock.shutdown(socket.SHUT_RDWR)  # wakes up a thread blocked in recv()
    except OSError:
        pass
    try:
        sock.close()
    except OSError:
        pass


def _inflate(inflater, data: bytes) -> bytes:
    """Decompress `data`, refusing to expand into something absurdly large."""
    parts, total = [], 0
    while data:
        part = inflater.decompress(data, MAX_LINE)  # at most MAX_LINE bytes per step
        parts.append(part)
        total += len(part)
        if total > MAX_INFLATED:
            raise zlib.error("message too large")
        data = inflater.unconsumed_tail
    return b"".join(parts)


def _send_or_close(sock: socket.socket, msg: dict, compressor=None, traffic=None) -> bool:
    """
    Send, giving up after SEND_TIMEOUT. A failed or timed-out send may have written half a
    message, so the connection can't be trusted any more: close it (the reader thread then
    reports it as closed).
    """
    try:
        sent = send_msg(sock, msg, compressor)
        if traffic is not None:
            traffic.sent += sent
            traffic.sends += 1
        return True
    except OSError:
        _close_socket(sock)
        return False


def _reader(sock: socket.socket, events: queue.Queue, tag, traffic=None,
            inflate_after_welcome=False):
    """
    Runs in a background thread. Pushes ("msg", tag, dict) for every message received
    and ("closed", tag, None) once when the connection ends.

    inflate_after_welcome: the server's "welcome" message is plain text; everything after
    it is one continuous zlib stream, so switch to decompressing right after that message.
    """
    buf = b""
    inflater = None
    try:
        while True:
            try:
                chunk = sock.recv(4096)
            except socket.timeout:
                continue  # the socket has a timeout for *sending*; just keep waiting to receive
            if not chunk:
                break
            if traffic is not None:
                traffic.received += len(chunk)
            if inflater is not None:
                chunk = _inflate(inflater, chunk)
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if not line.strip():
                    continue
                try:
                    msg = json.loads(line.decode("utf-8"))
                except ValueError:
                    continue
                if isinstance(msg, dict):
                    events.put(("msg", tag, msg))
                    if inflate_after_welcome and inflater is None and msg.get("type") == "welcome":
                        inflater = zlib.decompressobj()
                        buf = _inflate(inflater, buf)  # anything already received is compressed
            if len(buf) > MAX_LINE:
                break
    except (OSError, zlib.error):
        pass
    events.put(("closed", tag, None))


class TcpLink:
    """One TCP connection, wrapped so the Server and Client don't have to know about sockets."""

    authenticated = False   # a direct connection still has to give the lobby code (if any)

    def __init__(self, sock, traffic):
        self.sock = sock
        self.traffic = traffic
        self.compressor = None

    def send(self, msg) -> bool:
        return _send_or_close(self.sock, msg, self.compressor, self.traffic)

    def enable_compression(self):
        self.compressor = zlib.compressobj(6)

    def close(self):
        _close_socket(self.sock)


# ---------------------------------------------------------------- server

class Server:
    def __init__(self, port: int = DEFAULT_PORT, code: str = "", dedicated: bool = False,
                 log=None):
        """
        code      - optional lobby code guests must give to join ("" = open lobby)
        dedicated - no local host player; the first person in is the leader (see server.py)
        log       - optional function(text) that gets a line for each notable event
        """
        self.port = port
        self.code = code or ""
        self.dedicated = dedicated
        self.log = log or (lambda text: None)
        self.ip = get_local_ip()
        self.host_token = secrets.token_hex(8)  # proves "I am the host" to our own server

        # limits (instance attributes so tests can shorten them)
        self.idle_timeout = IDLE_TIMEOUT
        self.join_timeout = JOIN_TIMEOUT
        self.max_connections = MAX_CONNECTIONS
        self.max_msgs_per_sec = MAX_MSGS_PER_SEC

        self.players = []   # [{"id", "name", "host"}] in join order ("host" = lobby leader)
        self.conns = {}     # connection id -> socket
        self.game = None    # an UnoGame while a game is running (the server is the referee)
        self.scores = {}    # leaderboard: name (lowercase) -> {"points", "wins", "games"}
        self._scored = False   # has the current game's result been added to the leaderboard yet?

        self.traffic = Traffic()   # everything this server sent / received (the data meter)
        self._addrs = {}        # connection id -> remote ip (for the log)
        self._opened = {}       # connection id -> when it connected
        self._last_seen = {}    # connection id -> when we last heard from it
        self._rate = {}         # connection id -> [window start, messages in window]
        self._bad_codes = []    # times of recent wrong-code attempts
        self._last_housekeeping = 0.0

        self._events = queue.Queue()
        self._listener = None
        self._accept_thread = None
        self._running = False
        self._ids = itertools.count(1)   # connection ids (shared by TCP and online-room players)
        self.relay = None        # a relay.RelayHost while an online room is open

    # -- lifecycle

    def start(self):
        """Raises OSError if the port can't be used (e.g. already in use)."""
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if os.name != "nt":  # on Windows this option would allow two servers on one port
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("0.0.0.0", self.port))
            listener.listen()
        except OSError:
            listener.close()
            raise
        listener.settimeout(0.1)  # so the accept thread can notice when we shut down
        self._listener = listener
        self._running = True
        self._accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._accept_thread.start()

    def close(self):
        if not self._running:
            return
        self._running = False
        for cid in list(self.conns):
            self._send(cid, {"type": "closed"})
        if self.relay:
            self.relay.stop()
        for link in list(self.conns.values()):
            link.close()
        self.conns.clear()
        self.players.clear()
        self.game = None
        for table in (self._addrs, self._opened, self._last_seen, self._rate):
            table.clear()
        # Wait for the accept thread to stop before closing the listener, so the port is
        # really free again when close() returns (hosting again right away must work).
        if self._accept_thread:
            self._accept_thread.join(timeout=1.0)
        if self._listener:
            self._listener.close()
        self.log("Server closed.")

    # -- background thread

    def _accept_loop(self):
        while self._running:
            try:
                sock, addr = self._listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            sock.settimeout(SEND_TIMEOUT)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            cid = next(self._ids)
            self._events.put(("connect", cid, (TcpLink(sock, self.traffic), addr[0])))
            threading.Thread(target=_reader, args=(sock, self._events, cid, self.traffic),
                             daemon=True).start()

    # -- main thread: call once per frame

    def update(self):
        now = time.monotonic()
        while True:
            try:
                kind, cid, data = self._events.get_nowait()
            except queue.Empty:
                break
            if kind == "connect":
                self._on_connect(cid, data, now)
            elif not self._running:
                continue
            elif kind == "msg":
                if cid in self.conns:  # (a connection we already dropped may still have mail queued)
                    self._last_seen[cid] = now
                    if self._rate_ok(cid, now):
                        self._handle(cid, data)
            elif kind == "closed":
                self._drop(cid)

        if self._running and now - self._last_housekeeping >= 1.0:
            self._last_housekeeping = now
            self._housekeeping(now)

    def _on_connect(self, cid, data, now):
        link, addr = data
        if not self._running or len(self.conns) >= self.max_connections:
            link.close()
            return
        self.conns[cid] = link
        self._addrs[cid] = addr
        self._opened[cid] = now
        self._last_seen[cid] = now

    def _rate_ok(self, cid, now) -> bool:
        window = self._rate.get(cid)
        if window is None or now - window[0] >= 1.0:
            self._rate[cid] = [now, 1]
            return True
        window[1] += 1
        if window[1] > self.max_msgs_per_sec:
            self.log(f"Dropped {self._addrs.get(cid, '?')}: sending too many messages")
            self._refuse(cid, "Too many messages. Slow down.")
            return False
        return True

    def _housekeeping(self, now):
        """Drop connections that never said who they are, and ones that went silent."""
        joined = {p["id"] for p in self.players}
        for cid in list(self.conns):
            if not self._running:
                break
            if cid not in self.conns:
                continue
            if cid not in joined and now - self._opened.get(cid, now) > self.join_timeout:
                self._drop(cid)
            elif now - self._last_seen.get(cid, now) > self.idle_timeout:
                who = next((p["name"] for p in self.players if p["id"] == cid), "A connection")
                self.log(f"{who} timed out (no response)")
                self._drop(cid)

    def _handle(self, cid, msg):
        kind = msg.get("type")
        if kind == "ping":
            t = msg.get("t")
            self._send(cid, {"type": "pong", "t": t if isinstance(t, (int, float)) else None})
            return
        if kind == "join":
            self._on_join(cid, msg)
            return
        player = next((p for p in self.players if p["id"] == cid), None)
        if player is None:
            return  # not joined (yet), ignore everything else
        if kind == "start":
            self._on_start(player)
        elif kind == "to_lobby":
            self._on_to_lobby(player)
        elif kind in ("play", "draw", "pass"):
            self._on_move(player, kind, msg)
        elif kind == "resync":
            self._on_resync(player)

    def _name_taken(self, name: str) -> bool:
        wanted = name.casefold()
        reserved = not self.dedicated and wanted == HOST_NAME.casefold()
        return reserved or any(p["name"].casefold() == wanted for p in self.players)

    def _refuse(self, cid, message):
        self._send(cid, {"type": "error", "message": message})
        self._drop(cid)

    def _check_code(self, supplied) -> str:
        """"" if the code is fine, otherwise the reason it isn't."""
        if not self.code:
            return ""
        now = time.monotonic()
        self._bad_codes = [t for t in self._bad_codes if now - t < BAD_CODE_WINDOW]
        if len(self._bad_codes) >= BAD_CODE_LIMIT:
            return "Too many wrong codes. Wait a minute and try again."
        supplied = str(supplied or "")
        if hmac.compare_digest(supplied.encode("utf-8"), self.code.encode("utf-8")):
            return ""
        self._bad_codes.append(now)
        return "This lobby needs a code." if not supplied else "Wrong lobby code."

    def _on_join(self, cid, msg):
        known = next((p for p in self.players if p["id"] == cid), None)
        if known is not None:
            # A repeated join: over a relay the welcome may have been lost, so say it again.
            self._send(cid, {"type": "welcome", "id": cid})
            self._on_resync(known)
            return
        if msg.get("v") != PROTOCOL_VERSION:
            self._refuse(cid, "Your game version doesn't match the host's. "
                              "Everyone needs the same game files.")
            return
        if self.game is not None:
            self._refuse(cid, "A game is already in progress.")
            return
        if len(self.players) >= MAX_PLAYERS:
            self._refuse(cid, "The lobby is full.")
            return

        has_leader = any(p["host"] for p in self.players)
        local_host = (not self.dedicated and not has_leader
                      and msg.get("token") == self.host_token)
        if local_host:
            name = HOST_NAME  # the person running the server needs no code
        else:
            link = self.conns.get(cid)
            # Knowing the room code is the password for an online room (it is the encryption key).
            problem = "" if getattr(link, "authenticated", False) else self._check_code(msg.get("code"))
            if problem:
                self.log(f"Refused {self._addrs.get(cid, '?')}: {problem}")
                self._refuse(cid, problem)
                return
            name = clean_name(msg.get("name"))
            if not name:
                self._refuse(cid, "Please enter a username.")
                return
            if self._name_taken(name):
                self._refuse(cid, f'The username "{name}" is already taken. Pick another one.')
                return

        leader = local_host or (self.dedicated and not has_leader)
        self.players.append({"id": cid, "name": name, "host": leader})
        self.log(f"{name} joined from {self._addrs.get(cid, '?')}"
                 + (" (lobby leader)" if leader else ""))
        self._send(cid, {"type": "welcome", "id": cid})   # the last plain-text message...
        self.conns[cid].enable_compression()              # ...everything after is compressed
        self._broadcast_lobby()

    def _on_start(self, player):
        if not player["host"] or self.game is not None:
            return
        if len(self.players) < MIN_PLAYERS:
            self._send(player["id"], {"type": "notice",
                                      "message": f"Need at least {MIN_PLAYERS} players to start."})
            return
        self.game = UnoGame([(p["id"], p["name"]) for p in self.players])
        self._scored = False
        self.log(f"Game started with {len(self.players)} players")
        self._broadcast_state()

    def _on_to_lobby(self, player):
        if not player["host"] or self.game is None or not self.game.over:
            return
        self.game = None
        for p in self.players:
            self._send(p["id"], {"type": "to_lobby"})
        self._broadcast_lobby()

    def _on_move(self, player, kind, msg):
        if self.game is None:
            return
        cid = player["id"]
        if kind == "play":
            card_id = msg.get("card")
            if not isinstance(card_id, int):
                return
            error = self.game.play(cid, card_id, msg.get("color"))
        elif kind == "draw":
            error = self.game.draw(cid)
        else:
            error = self.game.pass_turn(cid)

        if error:
            self._send(cid, {"type": "notice", "message": error})
        else:
            self._game_changed()

    def _drop(self, cid):
        link = self.conns.pop(cid, None)
        if link:
            link.close()
        for table in (self._addrs, self._opened, self._last_seen, self._rate):
            table.pop(cid, None)

        player = next((p for p in self.players if p["id"] == cid), None)
        if player is None:
            return
        self.players.remove(player)
        self.log(f'{player["name"]} left')

        if player["host"]:
            if not self.dedicated:
                self.close()  # a hosted lobby (and any game) ends with its host
                return
            if self.players:  # a dedicated lobby carries on: the next person takes over
                self.players[0]["host"] = True
                self.log(f'{self.players[0]["name"]} is now the lobby leader')

        if self.game is not None:
            self.game.remove_player(cid)
            self._game_changed()
        if not self.players:  # empty dedicated lobby: forget everything for the next group
            self.game = None
            self.scores.clear()
            self._scored = False
        self._broadcast_lobby()

    # -- sending (main thread only)

    def _send(self, cid, msg):
        link = self.conns.get(cid)
        if link:
            link.send(msg)  # on failure the reader thread (or the heartbeat) reports a dead connection

    def _game_changed(self):
        """After every change to the game: bank the points once it's over, then tell everyone."""
        game = self.game
        if game is not None and game.over and not self._scored:
            self._scored = True
            for pid, points in game.points.items():
                entry = self.scores.setdefault(game.names[pid].casefold(),
                                               {"points": 0, "wins": 0, "games": 0})
                entry["points"] += points
                entry["games"] += 1
                if pid == game.winner:
                    entry["wins"] += 1
            self.log(f"Game over. Winner: {game.names[game.winner]}")
        self._broadcast_state()

    def _stats(self, name: str) -> dict:
        return self.scores.get(name.casefold(), {"points": 0, "wins": 0, "games": 0})

    def _broadcast_state(self):
        """Every player gets their own view: their hand, but only card counts for others."""
        if self.game is None:
            return
        for p in list(self.players):
            self._send(p["id"], {"type": "state", "game": self.game.view(p["id"])})

    def _lobby_msg(self):
        return {"type": "lobby",
                "players": [{**p, **self._stats(p["name"])} for p in self.players]}

    def _broadcast_lobby(self):
        msg = self._lobby_msg()
        for p in list(self.players):
            self._send(p["id"], msg)

    def _on_resync(self, player):
        """A client thinks it missed something: send it the lobby and the current game state."""
        cid = player["id"]
        self._send(cid, self._lobby_msg())
        # The last message carries "sync": it tells the client the repair has fully arrived.
        # (If the client doesn't see it, it just asks again.)
        if self.game is not None:
            self._send(cid, {"type": "state", "game": self.game.view(cid), "sync": 1})
        else:
            self._send(cid, {"type": "to_lobby", "sync": 1})

    # -- online room (friends join with a room code through a public relay server)

    def start_relay(self, brokers=None):
        """Also open an online room. Non-blocking: watch room_status / room_code."""
        if self.relay is None and self._running:
            self.relay = relay.RelayHost(brokers or relay.load_brokers(), self._events,
                                         self.traffic, self.log, lambda: next(self._ids))
            self.relay.start()

    @property
    def room_status(self) -> str:
        """"off", "connecting", "online", "reconnecting" or "error"."""
        return self.relay.status if self.relay else "off"

    @property
    def room_code(self) -> str:
        return self.relay.code if self.relay and self.relay.status in ("online", "reconnecting") else ""

    @property
    def room_detail(self) -> str:
        return self.relay.detail if self.relay else ""


# ---------------------------------------------------------------- client

class Client:
    """
    status: "idle" -> "connecting" -> "connected"
            or "failed"  (never got into a lobby; see .message)
            or "closed"  (was in a lobby and lost it; see .message)
    """

    def __init__(self):
        self.status = "idle"
        self.message = ""
        self.my_id = None
        self.players = []   # lobby players
        self.game = None    # latest game state from the server (None while in the lobby)
        self.toast = ""     # last "move refused" message from the server...
        self.toast_seq = 0  # ...and a counter that goes up each time a new one arrives
        self.ping_ms = None  # round-trip time to the server, once measured
        self.traffic = Traffic()  # bytes this client sent / received (the data meter)

        self.idle_timeout = IDLE_TIMEOUT
        self._events = queue.Queue()
        self._link = None        # a TcpLink or a relay.RelayGuest, once connected
        self._relay_mode = False
        self._closing = False
        self._lock = threading.Lock()
        self._started = 0.0
        self._last_recv = 0.0
        self._last_ping = 0.0
        self._last_resync = 0.0
        self._resync_wanted = False   # we noticed a gap and haven't been repaired yet

    @property
    def is_host(self) -> bool:
        """Am I the lobby leader (the one who can start games)?"""
        return any(p.get("id") == self.my_id and p.get("host") for p in self.players)

    def connect(self, host: str, port: int, token=None, name: str = "", code: str = ""):
        self.status = "connecting"
        self._started = time.monotonic()
        threading.Thread(target=self._run, args=(host, port, token, name, code),
                         daemon=True).start()

    def connect_room(self, code: str, name: str):
        """Join an online room by its room code (through a relay server, see relay.py)."""
        self.status = "connecting"
        self._relay_mode = True
        self._started = time.monotonic()
        threading.Thread(target=self._run_room, args=(code, name), daemon=True).start()

    def send(self, msg: dict):
        link = self._link
        if link:
            link.send(msg)

    def close(self):
        with self._lock:
            self._closing = True
            link, self._link = self._link, None
        if link:
            link.close()

    # -- background thread (becomes the reader thread once connected)

    def _run(self, host, port, token, name, code):
        try:
            sock = socket.create_connection((host, port), timeout=CONNECT_TIMEOUT)
        except socket.gaierror:
            self._events.put(("failed", None,
                              f'Could not find "{host}". Check the address for typos.'))
            return
        except ConnectionRefusedError:
            self._events.put(("failed", None,
                              f"{host}:{port} refused the connection. Is the lobby open "
                              f"and is the port right?"))
            return
        except socket.timeout:
            self._events.put(("failed", None,
                              f"No answer from {host}:{port}. It may be unreachable, or a "
                              f"firewall or router is blocking it."))
            return
        except OSError:
            self._events.put(("failed", None, f"Could not connect to {host}:{port}."))
            return
        sock.settimeout(SEND_TIMEOUT)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)

        with self._lock:
            if self._closing:  # close() was called while we were connecting
                sock.close()
                return
            self._link = TcpLink(sock, self.traffic)

        try:
            self.traffic.sent += send_msg(sock, {"type": "join", "v": PROTOCOL_VERSION,
                                                 "token": token, "name": name, "code": code})
            self.traffic.sends += 1
        except OSError:
            pass  # _reader below will report the closed connection
        _reader(sock, self._events, None, self.traffic, inflate_after_welcome=True)

    def _run_room(self, code, name):
        guest = None
        try:
            guest = relay.RelayGuest(code, self._events, self.traffic, relay.load_brokers())
            guest.connect()
        except ValueError as problem:
            self._events.put(("failed", None, str(problem)))
            return
        except relay.RelayError as problem:
            self._events.put(("failed", None, str(problem)))
            return
        with self._lock:
            if self._closing:
                guest.close()
                return
            self._link = guest
        # A relay can lose a message, so keep knocking until the host welcomes us.
        join = {"type": "join", "v": PROTOCOL_VERSION, "token": None, "name": name, "code": ""}
        while not self._closing and self.status == "connecting":
            guest.send(join)
            for _ in range(20):
                if self._closing or self.status != "connecting":
                    break
                time.sleep(0.1)

    # -- main thread: call once per frame

    def update(self):
        now = time.monotonic()
        while True:
            try:
                kind, _, data = self._events.get_nowait()
            except queue.Empty:
                break
            if kind == "msg":
                self._last_recv = now
                self._handle(data, now)
            elif kind == "gap":
                self._request_resync(now)
            elif kind == "failed":
                self._end("failed", data)
            elif kind == "closed":
                if self.status == "connected":
                    self._end("closed", "Lost connection to the relay server." if self._relay_mode
                              else "Lost connection to the server.")
                elif self.status == "connecting":
                    self._end("failed", "Lost connection to the relay server."
                              if self._relay_mode else "The server closed the connection.")

        if self._resync_wanted and self.status == "connected":
            self._request_resync(now)

        if self.status == "connecting" and now - self._started > CONNECT_DEADLINE:
            self._end("failed", "Nobody answered in that room. Check the room code, and make sure "
                                "the host has the lobby open." if self._relay_mode
                      else "The server did not answer in time.")
            self.close()
        elif self.status == "connected":
            if now - self._last_ping >= HEARTBEAT_EVERY:
                self._last_ping = now
                self.send({"type": "ping", "t": int(now * 1000)})
            if now - self._last_recv > self.idle_timeout:
                self._end("closed", "Lost connection to the server (it stopped responding).")
                self.close()

    def _request_resync(self, now):
        """We noticed a gap in the host's messages: ask for the current state (at most every 2 s)."""
        self._resync_wanted = True
        if now - self._last_resync >= 2.0:
            self._last_resync = now
            self.send({"type": "resync"})

    def _handle(self, msg, now):
        kind = msg.get("type")
        if msg.get("sync"):
            self._resync_wanted = False   # the repair we asked for has arrived
        if kind == "welcome":
            self.my_id = msg.get("id")
            self.status = "connected"
            self._last_ping = now
        elif kind == "pong":
            t = msg.get("t")
            if isinstance(t, (int, float)):
                rtt = max(0.0, int(now * 1000) - t)
                self.ping_ms = int(rtt if self.ping_ms is None else 0.7 * self.ping_ms + 0.3 * rtt)
        elif kind == "lobby":
            players = msg.get("players", [])
            if isinstance(players, list):
                self.players = [p for p in players if isinstance(p, dict)]
        elif kind == "state":
            game = msg.get("game")
            if isinstance(game, dict):
                self.game = game
        elif kind == "to_lobby":
            self.game = None
        elif kind == "notice":
            self.toast = str(msg.get("message", ""))
            self.toast_seq += 1
        elif kind == "closed":
            self._end("closed", "The lobby was closed.")
        elif kind == "error":
            self._end("failed", str(msg.get("message", "Could not join.")))

    def _end(self, status, message):
        if self.status in ("failed", "closed"):
            return  # keep the first (most specific) reason
        self.status = status
        self.message = message
