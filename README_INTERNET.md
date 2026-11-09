# Playing UNO over the internet

On the same Wi-Fi you can host a lobby and share the address it shows. Over the internet there
is one catch: **your friends' computers must be able to reach the host's computer**, and most
home connections don't allow that by default (routers block incoming connections, and many
internet providers share one public address between many customers, called CGNAT).

Pick whichever of these fits you. All of them use the same game files.

| Option | Who installs something | Cost | Best when |
|---|---|---|---|
| **Online room (built in)** | nobody | free | you just want to type a code and play |
| Tailscale | everyone | free (small groups) | you want a private network, even behind CGNAT |
| playit.gg tunnel | only the host | free | you want a fixed address for the host |
| Always-on server | nobody at home | a small server | you play often and don't want to "host" |
| Router port forwarding | nobody | free | your router allows it (not behind CGNAT) |

Everyone must have the **same version of the game files**. If versions differ, joining fails
with a clear message.

---

## Online room (built in, no setup)

1. The host: **Play, Host Game**, leave **Also open an online room** ticked, **Open Lobby**.
2. The lobby shows a **room code** like `K7QX-M2PD-9TNA`. Press **Copy** and send it to friends.
3. Friends: **Play, Join Game**, stay on the **Room code** tab, type (or Ctrl+V paste) their name
   and the code, and press Join.

It works from behind home routers and CGNAT, because nobody has to accept an incoming
connection: the host and every guest connect *outward* to a free public relay server (an "MQTT
broker") and leave messages for each other there.

**What to know about it (please read, it is honest rather than a sales pitch):**

- **The relay servers are free public test servers shared by everyone** (the game tries
  `broker.emqx.io`, `broker.hivemq.com` and `test.mosquitto.org`, in that order). Their
  operators give **no guarantee** that they stay online, and they ask users not to abuse them.
  The game sends only a few small messages a second to be polite. If they ever go away, run your
  own relay (next section) or use another option on this page.
- **I could not test against those real servers** (the environment I built this in has no
  internet). It was tested thoroughly against the bundled `mini_broker.py`, and the MQTT bytes
  were checked against the MQTT 3.1.1 specification. Please run **`python check_online.py`** on
  your computer once: it tells you in a few seconds whether online rooms work on your network.
- **Messages are end-to-end encrypted and signed** with a key made from the room code, so the
  relay (and anyone watching it) sees only scrambled bytes and cannot read hands or fake moves.
  The mailbox name is derived from the code too, so strangers can't find your room. This uses
  standard building blocks from Python's standard library (PBKDF2, HMAC-SHA256), but I combined
  them myself and it has not been reviewed by a cryptographer. It is meant to keep strangers out
  of a card game, not to protect secrets. **Keep the room code private**: anyone with it can join
  (and, with a modified game, could peek at other players' hands).
- The relay can see *that* the room exists and when messages are sent, but not what they say.
- It needs outgoing access to port **1883**. Some school, work or public networks block that.
  `check_online.py` will tell you.
- Messages can occasionally be lost on a relay. The game numbers its messages and asks the host
  to resend the current state when it notices a gap, so a lost message heals itself within a
  couple of seconds. (Tested with 12 percent of all messages deliberately dropped.)
- The host's room closes when the host closes the lobby. If the relay server drops for a
  moment, the host reconnects by itself and the **same code keeps working**.

### Check it works: `check_online.py`

```
python check_online.py
python check_online.py --broker my.server.address:1883
```

### Run your own relay (so nobody can take it away)

`mini_broker.py` is a tiny relay server using only Python. On any always-on computer with a
public address (see "Always-on server" below for how to open the port):

```
python3 mini_broker.py            # listens on port 1883
```

Then on **every player's computer**, create a file `brokers.json` next to the game files with
the same content (the order matters, it is part of the room code):

```
[["your.server.address", 1883, false]]
```

The third value turns TLS on if your broker supports it. It has no passwords, so anyone who
finds it can use it as a relay: don't run it on a machine that matters. Messages are encrypted
anyway, so it can't read your games.

---

## Tailscale (a private network between your devices)

Tailscale makes your computers behave as if they were on one Wi-Fi network, wherever they are.
At the time of writing its free plan covers up to 6 people (check tailscale.com/pricing, it has
changed before).

1. Everyone installs Tailscale and signs in. The host invites the others to their network
   (Tailscale admin page, "Users", then invite), or shares the host's machine with them.
2. The host runs the game: **Play, Host Game, Open Lobby**.
3. The host finds their Tailscale address (it starts with `100.`): click the Tailscale icon, or
   run `tailscale ip -4`.
4. Friends: **Play, Join Game**, open the **Address** tab, type their name and the host's
   Tailscale address, then Join.

## playit.gg (a free tunnel, only the host installs it)

A tunnel gives the host's lobby a public address without touching the router.

1. The host makes a free account at playit.gg and installs their agent program.
2. In playit.gg, create a **TCP** tunnel that points to local port **5555** (the game's default).
   (Their website changes now and then; look for "custom TCP" / "custom game server".)
3. playit.gg shows a public address like `something.at.ply.gg:7261`.
4. The host opens the lobby in the game and **keeps the playit agent running**.
5. Friends: **Join Game**, **Address** tab, paste that address (the `:7261` part is the port, and
   the game understands it), enter a name, Join.

Other tunnel services that offer plain TCP tunnels work the same way, as long as they give you a
`name:port` address. Pasting a `tcp://name:port` address works too.

## An always-on server (nobody hosts from home)

Run `server.py` on any computer that stays on and has a public IP address: a small cloud server,
a Raspberry Pi with port forwarding, an old PC. It needs only **Python 3.8+**. No pygame, no
window. Copy these files to it: `server.py`, `network.py`, `uno.py`, `relay.py`.

```
python3 server.py --code mysecret            # listens on port 5555
python3 server.py --port 6000 --code mysecret
python3 server.py --online                   # ALSO open an online room (prints the room code)
```

- The first person to join becomes the lobby leader and can start games. If they leave,
  the next person takes over. When everyone has left, the lobby resets, scores included.
- `--online` is useful when the server sits behind a home router: friends join with the room
  code and no port needs opening.
- To be reachable directly, open **TCP 5555** in the server's firewall *and* in your cloud
  provider's network rules. On Ubuntu: `sudo ufw allow 5555/tcp`.
- Friends: **Join Game**, **Address** tab, enter the server's IP address (and the lobby code).

To keep it running after you close the terminal, either use `tmux`/`screen`, or on Linux make it
a service. Save this as `/etc/systemd/system/uno.service` (change the user and folder):

```
[Unit]
Description=UNO game server
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/uno
ExecStart=/usr/bin/python3 server.py --port 5555 --code mysecret
Restart=always

[Install]
WantedBy=multi-user.target
```

then `sudo systemctl enable --now uno` (and `journalctl -u uno -f` to watch the log).

## Router port forwarding

1. Give the host's computer a fixed address on your home network (a "DHCP reservation").
2. In the router's settings, forward **TCP port 5555** to that computer.
3. Find your public IP (search "what is my IP") and give it to your friends (Address tab).

This only works if your router has a real public address. Check: compare the "WAN IP" shown in
your router's status page with the "what is my IP" result. If they are different, your provider
uses CGNAT and port forwarding cannot work. Use an online room, Tailscale or a tunnel instead.

On Windows, the first time you host, a firewall prompt appears for Python: allow it.

---

## Data usage (for metered connections)

The game is built to be light. Measured on real games (not estimates), two back-to-back 1v1
games of about 60 to 100 moves:

| | Per move (guest) | Two 1v1 games (guest) |
|---|---|---|
| Original, before optimizing | about 1,250 B | about 60 to 110 KB |
| **Direct connection** (now) | about 86 B | about 5.5 KB |
| **Online room** (now) | about 343 B | about 20 to 35 KB |

An online room costs about 4 times more than a direct connection, because each relay message
must be encrypted and compressed on its own (a relay can lose messages, so one long compressed
stream is not safe there), and it carries the relay's addressing. It is still small.

Idle in a lobby, expect about 90 KB per player per hour (a tiny heartbeat every 10 seconds).
The "Data" number in the game's corner counts message bytes only; each message also costs roughly
50 bytes of packet headers, so your phone's own counter will read a few times higher.

If you host through a tunnel, remember the **host** uploads to everyone. To use even less, close
the lobby when you are not playing.

## Lobby code (direct joins)

Hosting from the **Host Game** screen lets you set a *code for direct joins*; on a dedicated
server use `--code`. Without one, anyone who finds the address can join directly. This code is a
shared secret for the room, **not** a secure password, and it is sent without encryption, so
never reuse a real one. After 8 wrong codes in a minute, joining with a code pauses for a minute.
(Online rooms don't use it: the room code itself is the password.)

## When something goes wrong

| Message | Usually means |
|---|---|
| That room code doesn't look right. | A typo. Room codes have 12 letters and digits (no I, O, 0 or 1). |
| Nobody answered in that room. | Wrong code, or the host's lobby isn't open / has no online room. |
| Could not reach the relay server ... | No internet, port 1883 blocked, or that free server is down. Run `check_online.py`. |
| Online room unavailable (host's lobby) | The host could not reach any relay server. It keeps retrying. Friends can still join directly. |
| Could not find "...". Check the address for typos. | (Address tab) The name doesn't exist, or you have no internet. |
| ... refused the connection. | The address is right but nothing is listening: the lobby isn't open yet, the port is wrong, or the tunnel agent isn't running. |
| No answer from ... | Packets are being dropped: a firewall or router is blocking the port, you're behind CGNAT, or the IP is wrong. |
| This lobby needs a code. / Wrong lobby code. | (Address tab) Ask the host for the code. |
| Your game version doesn't match the host's. | Everyone must use the same game files. |
| The username "..." is already taken. | Pick another name. |
| Lost connection to the server / relay server | The internet dropped, or the host closed the game. |

## Good to know

- Up to 10 players per lobby.
- A connection that goes silent for about 30 seconds is dropped, so one frozen player can't
  stall everyone else. A player who drops mid-game cannot rejoin that game: they are ranked
  last for it, and the others carry on.
- The small readout at the bottom-left shows **Ping** (round-trip time; under about 150 ms feels
  instant for a card game) and **Data** used so far. When you host, it shows how much your
  connection has sent to and received from your guests instead.
- Press **F2** anywhere to switch between light and dark mode.
- The networking was tested on a single computer only (many simulated players, dropped and
  silent connections, message loss, forged and replayed messages, relay outages), not across the
  real internet, so router and mobile-hotspot quirks may still surprise you. If something behaves
  oddly, note the exact message shown.
