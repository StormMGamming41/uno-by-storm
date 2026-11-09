"""
Online rooms: play over the internet with a short room code. No port forwarding, no VPN,
nothing for your friends to install.

How it works
  The host and the guests never connect to each other. They all connect OUTWARD to a free
  public "MQTT broker" (a message post office that anyone can use for testing) and leave
  messages for each other in a mailbox whose name only people with the room code can work out.
  Outgoing connections work from behind any home router, even when the internet provider
  shares one address between many customers (CGNAT), which is what stops normal hosting.

  Everything is end-to-end encrypted and authenticated with a key made from the room code
  (PBKDF2 -> HMAC-SHA256 stream cipher + HMAC tag, all from Python's standard library). The
  broker only ever sees scrambled bytes and a mailbox name that doesn't reveal the code.
  This combination of standard building blocks is not an audited library: it is meant to
  keep strangers out of a card game, not to protect secrets.

  Messages can occasionally be lost on this kind of relay, so every message carries a counter.
  A guest who notices a gap asks the host to re-send the current lobby/game state.

Used by network.py. No pygame in here.
"""

import hashlib
import hmac
import json
import os
import secrets
import socket
import ssl
import struct
import threading
import time
import zlib

ROOT = "uno-card-game"
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # 32 symbols; no I, O, 0, 1 (easy to mix up)
CODE_LEN = 12                                   # 1 symbol picks the relay server, 11 are random (55 bits)
KDF_ROUNDS = 100_000
SALT = b"uno-card-game/room/v1"
MAX_PACKET = 1 << 20      # biggest MQTT packet we accept from a broker
MAX_PLAIN = 256 * 1024    # biggest message we accept after decrypting/decompressing
MAX_PEERS = 40
SEND_TIMEOUT = 3.0
CONNECT_TIMEOUT = 6.0
KEEPALIVE = 60            # MQTT keepalive in seconds

# The public relay servers, tried in this order. A room code remembers which one the host got
# (its first character), so guests always go to the same one. All of them are free test servers
# with no guarantee of service. Put your own list in brokers.json to override: [["host", 1883, false]]
DEFAULT_BROKERS = [
    ("broker.emqx.io", 1883, False),
    ("broker.hivemq.com", 1883, False),
    ("test.mosquitto.org", 1883, False),
]
BROKERS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "brokers.json")


def load_brokers():
    try:
        with open(BROKERS_FILE, "r", encoding="utf-8") as f:
            brokers = [(str(h), int(p), bool(t)) for h, p, t in json.load(f)]
        if brokers:
            return brokers
    except (OSError, ValueError, TypeError):
        pass
    return list(DEFAULT_BROKERS)


class RelayError(Exception):
    """The message is safe to show to a player."""


class MqttError(Exception):
    pass


# ---------------------------------------------------------------- room codes

def new_room_code(broker_index: int) -> str:
    if not 0 <= broker_index < len(ALPHABET):
        raise ValueError("too many brokers")
    return ALPHABET[broker_index] + "".join(secrets.choice(ALPHABET) for _ in range(CODE_LEN - 1))


def format_code(code: str) -> str:
    return "-".join(code[i:i + 4] for i in range(0, len(code), 4))


def parse_room_code(text):
    """-> (normalized code, index of the relay server it uses). Raises ValueError for the player."""
    cleaned = "".join(ch for ch in str(text).upper() if ch not in " -_")
    if len(cleaned) != CODE_LEN or any(ch not in ALPHABET for ch in cleaned):
        raise ValueError("That room code doesn't look right. It has 12 letters and "
                         "digits, like K7QX-M2PD-9TNA.")
    return cleaned, ALPHABET.index(cleaned[0])


# ---------------------------------------------------------------- encryption

# A preset dictionary makes each message compress well ON ITS OWN (a relay can lose messages,
# so we can't use one long compression stream like the direct connection does). Both sides
# must have the identical dictionary, so it is part of the protocol: never edit it casually.
_ZDICT = (
    b'{"f":"h","n":12,"m":{"type":"pong","t":1234567}}{"f":"a1b2c3d4","n":7,"m":{"type":"ping","'
    b't":1234567}}{"f":"a1b2c3d4","n":1,"m":{"type":"join","v":3,"token":null,"name":"Alice","co'
    b'de":""}}{"f":"h","n":1,"m":{"type":"welcome","id":2}}{"f":"h","n":2,"m":{"type":"lobby","p'
    b'layers":[{"id":1,"name":"Host","host":true,"points":3,"wins":1,"games":2},{"id":2,"name":"'
    b'Alice","host":false,"points":1,"wins":0,"games":2}]}}{"f":"a1b2c3d4","n":9,"m":{"type":"pl'
    b'ay","card":42,"color":null}}{"f":"a1b2c3d4","n":10,"m":{"type":"draw"}}{"f":"a1b2c3d4","n"'
    b':11,"m":{"type":"pass"}}{"f":"a1b2c3d4","n":3,"m":{"type":"start"}}{"f":"a1b2c3d4","n":4,"'
    b'm":{"type":"to_lobby"}}{"f":"a1b2c3d4","n":5,"m":{"type":"resync"}}{"f":"a1b2c3d4","n":6,"'
    b'm":{"type":"bye"}}{"f":"h","n":5,"m":{"type":"to_lobby"}}{"f":"h","n":6,"m":{"type":"notic'
    b'e","message":"It\'s not your turn."}}{"f":"h","n":7,"m":{"type":"closed"}}{"f":"h","n":8,"m'
    b'":{"type":"error","message":"The username \\"Bob\\" is already taken. Pick another one."}}{"'
    b'f":"h","n":9,"m":{"type":"error","message":"Your game version doesn\'t match the host\'s. Ev'
    b'eryone needs the same game files."}}{"f":"h","n":33,"m":{"type":"state","game":{"hand":[{"'
    b'id":41,"color":"yellow","value":"8"},{"id":68,"color":"green","value":"9"},{"id":74,"color'
    b'":"green","value":"draw2"},{"id":27,"color":"yellow","value":"1"},{"id":55,"color":"green"'
    b',"value":"3"},{"id":30,"color":"yellow","value":"3"},{"id":54,"color":"green","value":"2"}'
    b',{"id":97,"color":"blue","value":"reverse"},{"id":72,"color":"green","value":"reverse"},{"'
    b'id":15,"color":"red","value":"8"}],"playable":[54,15],"drawn":null,"players":[{"id":1,"nam'
    b'e":"Alice","count":10,"place":null},{"id":2,"name":"Bob","count":2,"place":null},{"id":3,"'
    b'name":"Carol","count":5,"place":null}],"place":null,"current":1,"direction":1,"top":{"id":'
    b'4,"color":"red","value":"2"},"color":"red","draw_count":81,"over":false,"winner":null,"win'
    b'ner_name":null,"forfeit":false,"ranking":[],"log":["Alice passed.","Bob played Red 2.","Ca'
    b'rol drew a card.","Carol passed."],"events":[{"seq":9,"kind":"draw","pid":1,"count":1,"car'
    b'ds":[72]},{"seq":10,"kind":"play","pid":2,"card":{"id":12,"color":"red","value":"6"}},{"se'
    b'q":11,"kind":"play","pid":3,"card":{"id":8,"color":"red","value":"4"}},{"seq":12,"kind":"d'
    b'raw","pid":1,"count":1,"cards":[15]},{"seq":13,"kind":"play","pid":2,"card":{"id":4,"color'
    b'":"red","value":"2"}},{"seq":14,"kind":"draw","pid":3,"count":1}]}}}{"f":"h","n":40,"m":{"'
    b'type":"state","game":{"hand":[],"playable":[],"drawn":null,"players":[{"id":1,"name":"Alic'
    b'e","count":10,"place":null},{"id":2,"name":"Bob","count":2,"place":null},{"id":3,"name":"C'
    b'arol","count":5,"place":null}],"place":1,"current":null,"direction":1,"top":{"id":4,"color'
    b'":"red","value":"2"},"color":"red","draw_count":40,"over":true,"winner":2,"winner_name":"B'
    b'ob","forfeit":false,"ranking":[{"id":2,"name":"Bob","points":2},{"id":1,"name":"Alice","po'
    b'ints":1},{"id":3,"name":"Carol","points":0}],"log":["Bob played Red Skip.","Carol is skipp'
    b'ed.","Bob finished in 1st place!","Game over! Bob takes 1st place."],"events":[]}}}{"hand"'
    b':[{"id":0,"color":"red","value":"0"},{"id":1,"color":"red","value":"1"},{"id":2,"color":"r'
    b'ed","value":"2"},{"id":3,"color":"red","value":"3"},{"id":4,"color":"red","value":"4"},{"i'
    b'd":5,"color":"red","value":"5"},{"id":6,"color":"red","value":"6"},{"id":7,"color":"red","'
    b'value":"7"}]}played Red played Yellow played Green played Blue played Wild Draw 4, color p'
    b'layed Wild, color  draws 2 and is skipped. draws 4 and is skipped. is skipped.Direction re'
    b'versed. has UNO! drew a card. drew a card and had to pass. passed. finished in  place!Game'
    b' over!  takes 1st place. left the game.The game starts with a '
)


def _keystream(key: bytes, nonce: bytes, n: int) -> bytes:
    blocks = (n + 31) // 32
    return b"".join(hmac.new(key, nonce + i.to_bytes(4, "big"), "sha256").digest()
                    for i in range(blocks))[:n]


def _xor(data: bytes, stream: bytes) -> bytes:
    if not data:
        return b""
    return (int.from_bytes(data, "big") ^ int.from_bytes(stream, "big")).to_bytes(len(data), "big")


class RoomKeys:
    """Everything derived from a room code: the mailbox names and the encryption keys."""

    def __init__(self, code: str):
        derived = hashlib.pbkdf2_hmac("sha256", code.encode("ascii"), SALT, KDF_ROUNDS, 80)
        self.room = derived[:16].hex()
        self._enc = derived[16:48]
        self._mac = derived[48:80]

    def up_topic(self) -> str:        # guests -> host
        return f"{ROOT}/{self.room}/up"

    def down_topic(self, guest: str) -> str:   # host -> one guest
        return f"{ROOT}/{self.room}/down/{guest}"

    def seal(self, obj) -> bytes:
        raw = json.dumps(obj, separators=(",", ":")).encode("utf-8")
        co = zlib.compressobj(9, zlib.DEFLATED, 15, 9, zlib.Z_DEFAULT_STRATEGY, _ZDICT)
        body = co.compress(raw) + co.flush()
        nonce = os.urandom(12)
        cipher = _xor(body, _keystream(self._enc, nonce, len(body)))
        tag = hmac.new(self._mac, b"\x01" + nonce + cipher, "sha256").digest()[:16]
        return b"\x01" + nonce + cipher + tag

    def open(self, blob: bytes):
        """The decoded message, or None if it is forged, damaged or from another room."""
        if len(blob) < 1 + 12 + 16 or blob[0] != 1:
            return None
        nonce, cipher, tag = blob[1:13], blob[13:-16], blob[-16:]
        expected = hmac.new(self._mac, b"\x01" + nonce + cipher, "sha256").digest()[:16]
        if not hmac.compare_digest(tag, expected):
            return None
        try:
            body = _xor(cipher, _keystream(self._enc, nonce, len(cipher)))
            inflater = zlib.decompressobj(15, _ZDICT)
            raw = inflater.decompress(body, MAX_PLAIN)
            if inflater.unconsumed_tail or len(raw) >= MAX_PLAIN:
                return None
            return json.loads(raw.decode("utf-8"))
        except (zlib.error, ValueError):
            return None


# ---------------------------------------------------------------- a tiny MQTT 3.1.1 client

def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        digit, n = n % 128, n // 128
        out.append(digit | (128 if n else 0))
        if not n:
            return bytes(out)


def _mqtt_str(text: str) -> bytes:
    data = text.encode("utf-8")
    return struct.pack("!H", len(data)) + data


def take_packet(buf: bytearray):
    """Remove one complete MQTT packet from the front of buf -> (first byte, body), or None."""
    if len(buf) < 2:
        return None
    length, mult, i = 0, 1, 1
    while True:
        if i >= len(buf):
            return None
        byte = buf[i]
        length += (byte & 127) * mult
        i += 1
        if not byte & 128:
            break
        mult *= 128
        if mult > 128 ** 3:
            raise MqttError("bad packet length")
    if length > MAX_PACKET:
        raise MqttError("packet too large")
    if len(buf) < i + length:
        return None
    first, body = buf[0], bytes(buf[i:i + length])
    del buf[:i + length]
    return first, body


class MqttClient:
    """
    Just enough MQTT to publish and subscribe at QoS 0. Callbacks run on the reader thread:
    on_message(topic, payload) and on_close() (called exactly once when the link ends).
    `traffic` (optional) gets sent/received/sends counted, for the data meter.
    """

    def __init__(self, host, port, tls=False, traffic=None):
        self.host, self.port, self.tls = host, port, tls
        self.traffic = traffic
        self.on_message = None
        self.on_close = None
        self._sock = None
        self._send_lock = threading.Lock()
        self._acks = {}
        self._next_id = 0
        self._closed = False
        self._close_called = False
        self._last_sent = self._last_recv = time.monotonic()

    # -- connecting

    def connect(self, timeout=CONNECT_TIMEOUT):
        try:
            sock = socket.create_connection((self.host, self.port), timeout=timeout)
            if self.tls:
                sock = ssl.create_default_context().wrap_socket(sock, server_hostname=self.host)
            sock.settimeout(timeout)
            client_id = "uno-" + secrets.token_hex(6)
            body = (_mqtt_str("MQTT") + bytes([4, 2]) + struct.pack("!H", KEEPALIVE)
                    + _mqtt_str(client_id))
            sock.sendall(bytes([0x10]) + _varint(len(body)) + body)
            reply = b""
            while len(reply) < 4:                     # CONNACK is exactly 4 bytes
                chunk = sock.recv(4 - len(reply))
                if not chunk:
                    raise MqttError("the server closed the connection")
                reply += chunk
        except (OSError, ssl.SSLError) as error:
            raise MqttError(str(error) or error.__class__.__name__) from error
        if reply[0] != 0x20 or reply[3] != 0:
            sock.close()
            raise MqttError("the server refused the connection")
        sock.settimeout(SEND_TIMEOUT)   # sends give up after this; the reader just retries
        self._sock = sock
        self._last_sent = self._last_recv = time.monotonic()
        threading.Thread(target=self._read_loop, daemon=True).start()
        threading.Thread(target=self._keepalive_loop, daemon=True).start()

    def subscribe(self, topic, timeout=CONNECT_TIMEOUT):
        self._next_id = self._next_id % 65535 + 1
        pid, event = self._next_id, threading.Event()
        self._acks[pid] = [event, None]
        body = struct.pack("!H", pid) + _mqtt_str(topic) + b"\x00"
        self._send(bytes([0x82]) + _varint(len(body)) + body)
        if not event.wait(timeout):
            raise MqttError("the server did not confirm the subscription")
        if self._acks.pop(pid)[1] == 0x80:
            raise MqttError("the server refused the subscription")

    def publish(self, topic, payload: bytes):
        body = _mqtt_str(topic) + payload
        self._send(bytes([0x30]) + _varint(len(body)) + body)

    def close(self):
        if not self._closed:
            self._closed = True
            sock = self._sock
            if sock:
                try:
                    sock.sendall(b"\xe0\x00")
                except OSError:
                    pass
                for action in (lambda: sock.shutdown(socket.SHUT_RDWR), sock.close):
                    try:
                        action()
                    except OSError:
                        pass
        self._finish()

    # -- internals

    def _send(self, data: bytes):
        if self._closed or self._sock is None:
            raise MqttError("not connected")
        try:
            with self._send_lock:
                self._sock.sendall(data)
                self._last_sent = time.monotonic()
        except OSError as error:
            self.close()
            raise MqttError("connection lost") from error
        if self.traffic is not None:
            self.traffic.sent += len(data)
            self.traffic.sends += 1

    def _finish(self):
        if not self._close_called:
            self._close_called = True
            self._closed = True
            if self.on_close:
                self.on_close()

    def _read_loop(self):
        buf = bytearray()
        try:
            while not self._closed:
                try:
                    chunk = self._sock.recv(65536)
                except socket.timeout:
                    continue
                if not chunk:
                    break
                self._last_recv = time.monotonic()
                if self.traffic is not None:
                    self.traffic.received += len(chunk)
                buf += chunk
                while True:
                    packet = take_packet(buf)
                    if packet is None:
                        break
                    self._dispatch(*packet)
        except (OSError, MqttError, ssl.SSLError):
            pass
        finally:
            self.close()

    def _dispatch(self, first, body):
        kind = first >> 4
        if kind == 3:                                         # PUBLISH
            qos = (first >> 1) & 3
            (topic_len,) = struct.unpack("!H", body[:2])
            topic = body[2:2 + topic_len].decode("utf-8", "replace")
            pos = 2 + topic_len
            if qos:
                if qos == 1:
                    self._send(b"\x40\x02" + body[pos:pos + 2])
                pos += 2
            if self.on_message:
                self.on_message(topic, body[pos:])
        elif kind == 9 and len(body) >= 3:                    # SUBACK
            (pid,) = struct.unpack("!H", body[:2])
            slot = self._acks.get(pid)
            if slot:
                slot[1] = body[2]
                slot[0].set()

    def _keepalive_loop(self):
        while not self._closed:
            time.sleep(1.0)
            now = time.monotonic()
            if now - self._last_recv > KEEPALIVE * 2:
                self.close()
            elif now - self._last_sent > KEEPALIVE / 2:
                try:
                    self._send(b"\xc0\x00")
                except MqttError:
                    return


# ---------------------------------------------------------------- the host's side

class _Peer:
    __slots__ = ("gid", "cid", "last_in", "out")

    def __init__(self, gid, cid, last_in):
        self.gid, self.cid, self.last_in, self.out = gid, cid, last_in, 0


class RelayPeerLink:
    """One guest as the Server sees them: looks like a connection, but it's a mailbox."""

    authenticated = True   # knowing the room code is the password, so no separate lobby code

    def __init__(self, host, peer):
        self._host, self._peer = host, peer

    def send(self, msg) -> bool:
        return self._host._send_to(self._peer, msg)

    def enable_compression(self):
        pass  # every relay message is compressed on its own

    def close(self):
        self._host._forget(self._peer)


class RelayHost:
    """
    Opens a room on a public broker and turns each guest's messages into the same
    ("connect"/"msg"/"closed") events a TCP connection would produce, so the Server
    doesn't care how a player arrived. Runs in background threads.
    """

    def __init__(self, brokers, events, traffic, log, new_id):
        self.brokers = list(brokers)
        self.events = events          # the Server's event queue
        self.traffic = traffic
        self.log = log
        self.new_id = new_id          # thread-safe: returns a fresh connection id
        self.status = "idle"          # idle / connecting / online / reconnecting / error
        self.detail = ""              # a sentence for the host when something is wrong
        self.code = ""                # the room code (once the room exists)
        self.broker = None            # (host, port, tls) in use
        self.rejected = 0             # forged / damaged messages ignored
        self._keys = None
        self._index = 0
        self._mqtt = None
        self._peers = {}
        self._dead = set()            # guest ids that left: their messages are never accepted again
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._lost = threading.Event()
        self._thread = None

    def start(self):
        self.status = "connecting"
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._lost.set()
        mqtt = self._mqtt
        if mqtt:
            mqtt.on_close = None
            mqtt.close()
        self.status = "idle"

    # -- connection management

    def _run(self):
        while not self._stop.is_set() and not self._open_room():
            self.status = "error"
            self._stop.wait(15)          # then try the whole list again
            if not self._stop.is_set():
                self.status = "connecting"
        while not self._stop.is_set():
            self._lost.wait()
            if self._stop.is_set():
                break
            self.status, self.detail = "reconnecting", "Lost the relay server. Reconnecting..."
            delay = 1.0
            while not self._stop.is_set():
                try:
                    self._connect(self._index)
                    self.log("Online room reconnected")
                    break
                except MqttError as error:
                    self.log(f"Relay reconnect failed: {error}")
                    self._stop.wait(delay)
                    delay = min(delay * 2, 20.0)

    def _open_room(self) -> bool:
        problems = []
        for index, (host, port, _tls) in enumerate(self.brokers[:len(ALPHABET)]):
            code = new_room_code(index)
            self._keys, self._index = RoomKeys(code), index
            try:
                self._connect(index)
            except MqttError as error:
                problems.append(f"{host}: {error}")
                self.log(f"Relay {host}:{port} unavailable: {error}")
                continue
            self.code = code
            self.log(f"Online room {format_code(code)} open via {host}")
            return True
        self.detail = "No relay server could be reached. " + (problems[0] if problems else "")
        return False

    def _connect(self, index):
        host, port, tls = self.brokers[index]
        mqtt = MqttClient(host, port, tls, self.traffic)
        mqtt.on_message = self._on_message
        mqtt.on_close = self._on_broker_closed
        mqtt.connect()
        try:
            mqtt.subscribe(self._keys.up_topic())
        except MqttError:
            mqtt.on_close = None
            mqtt.close()
            raise
        self._lost.clear()
        self._mqtt = mqtt
        self.broker = (host, port, tls)
        self.status, self.detail = "online", ""

    def _on_broker_closed(self):
        if not self._stop.is_set():
            self._lost.set()

    # -- guests

    def _on_message(self, topic, payload):
        keys = self._keys
        if keys is None or topic != keys.up_topic():
            return
        obj = keys.open(payload)
        if not isinstance(obj, dict):
            self.rejected += 1
            return
        gid, n, msg = obj.get("f"), obj.get("n"), obj.get("m")
        if (not isinstance(gid, str) or not 1 <= len(gid) <= 16 or not gid.isalnum()
                or not isinstance(n, int) or not isinstance(msg, dict)):
            self.rejected += 1
            return

        created = None
        with self._lock:
            if gid in self._dead:
                return
            peer = self._peers.get(gid)
            if peer is None:
                if msg.get("type") != "join":
                    unknown = True      # e.g. someone we timed out is still talking
                elif len(self._peers) >= MAX_PEERS:
                    return
                else:
                    unknown = False
                    peer = created = _Peer(gid, self.new_id(), n)
                    self._peers[gid] = peer
            else:
                unknown = False
                if n <= peer.last_in:
                    return              # a duplicate or a replayed message
                peer.last_in = n
        if unknown:
            self._publish_raw(gid, {"type": "error", "message":
                                    "You were removed from the room. Join again."})
            return
        if created:
            self.events.put(("connect", created.cid, (RelayPeerLink(self, created), "online")))
        if msg.get("type") == "bye":
            self.events.put(("closed", peer.cid, None))
        else:
            self.events.put(("msg", peer.cid, msg))

    def _publish_raw(self, gid, msg):
        mqtt, keys = self._mqtt, self._keys
        if mqtt and keys:
            try:
                mqtt.publish(keys.down_topic(gid), keys.seal({"f": "h", "n": 2 ** 40, "m": msg}))
            except MqttError:
                pass

    def _send_to(self, peer, msg) -> bool:
        mqtt, keys = self._mqtt, self._keys
        if mqtt is None or keys is None or self._lost.is_set():
            return False
        with self._lock:
            peer.out += 1
            n = peer.out
        try:
            mqtt.publish(keys.down_topic(peer.gid), keys.seal({"f": "h", "n": n, "m": msg}))
            return True
        except MqttError:
            return False

    def _forget(self, peer):
        with self._lock:
            self._peers.pop(peer.gid, None)
            self._dead.add(peer.gid)


# ---------------------------------------------------------------- the guest's side

class RelayGuest:
    """
    A guest's link to a room. send() takes a message dict; incoming messages arrive on the
    Client's event queue as ("msg", None, dict). A gap in the host's message counter puts
    ("gap", None, None) on the queue so the Client can ask for a fresh copy of the state.
    """

    def __init__(self, code, events, traffic, brokers):
        self.code, self.index = parse_room_code(code)
        self.events, self.traffic, self.brokers = events, traffic, list(brokers)
        self.gid = secrets.token_hex(4)
        self._keys = None
        self._mqtt = None
        self._out = 0
        self._last_in = 0
        self._lock = threading.Lock()
        self._closing = False

    def connect(self):
        """Slow (key derivation + network). Raises RelayError with a message for the player."""
        if self.index >= len(self.brokers):
            raise RelayError("This room code uses a relay server your copy of the game doesn't "
                             "know. Make sure everyone has the same game files.")
        host, port, tls = self.brokers[self.index]
        self._keys = RoomKeys(self.code)
        mqtt = MqttClient(host, port, tls, self.traffic)
        mqtt.on_message = self._on_message
        mqtt.on_close = self._on_closed
        try:
            mqtt.connect()
            mqtt.subscribe(self._keys.down_topic(self.gid))
        except MqttError as error:
            mqtt.on_close = None
            mqtt.close()
            raise RelayError(f"Could not reach the relay server ({host}). Check your internet "
                             f"connection. ({error})") from error
        self._mqtt = mqtt

    def send(self, msg) -> bool:
        mqtt, keys = self._mqtt, self._keys
        if mqtt is None or keys is None:
            return False
        with self._lock:
            self._out += 1
            n = self._out
        try:
            mqtt.publish(keys.up_topic(), keys.seal({"f": self.gid, "n": n, "m": msg}))
            return True
        except MqttError:
            return False

    def close(self):
        self._closing = True
        mqtt = self._mqtt
        if mqtt:
            try:
                self.send({"type": "bye"})
            except Exception:
                pass
            mqtt.on_close = None
            mqtt.close()

    def _on_closed(self):
        if not self._closing:
            self.events.put(("closed", None, None))

    def _on_message(self, topic, payload):
        keys = self._keys
        if keys is None or topic != keys.down_topic(self.gid):
            return
        obj = keys.open(payload)
        if not isinstance(obj, dict) or obj.get("f") != "h":
            return
        n, msg = obj.get("n"), obj.get("m")
        if not isinstance(n, int) or not isinstance(msg, dict):
            return
        if n <= self._last_in:
            return                       # duplicate / replay
        gap = n > self._last_in + 1
        self._last_in = n
        if gap:
            self.events.put(("gap", None, None))
        self.events.put(("msg", None, msg))
