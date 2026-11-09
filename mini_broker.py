#!/usr/bin/env python3
"""
A tiny MQTT 3.1.1 message broker, written to be run with nothing but Python.

Why it exists: the game's "online rooms" send messages through an MQTT broker. By default it
uses free public ones (see relay.py), but those are shared test servers that can disappear.
Run this on any always-on computer with a public address, point the game at it, and you have
your own relay that nobody else can take away.

    python3 mini_broker.py                  # listens on port 1883, all addresses
    python3 mini_broker.py --port 2883

Then list it in brokers.json next to the game files, on EVERY player's computer (same list,
same order):    [["your.server.address", 1883, false]]

It supports what the game needs and nothing more: CONNECT, SUBSCRIBE / UNSUBSCRIBE (with the
+ and # wildcards), PUBLISH at QoS 0 and 1, PING, DISCONNECT. No passwords, no saved messages.
Game messages are end-to-end encrypted, so this server can't read them. Because it has no
login, anyone who finds it can use it as a relay, so don't run it on a machine that matters.
"""

import argparse
import socket
import struct
import threading
import time

MAX_PACKET = 1 << 20
MAX_CLIENTS = 500


def _varint(n):
    out = bytearray()
    while True:
        digit, n = n % 128, n // 128
        out.append(digit | (128 if n else 0))
        if not n:
            return bytes(out)


def _take_packet(buf):
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
            raise ValueError("bad length")
    if length > MAX_PACKET:
        raise ValueError("packet too large")
    if len(buf) < i + length:
        return None
    first, body = buf[0], bytes(buf[i:i + length])
    del buf[:i + length]
    return first, body


def _matches(filter_, topic):
    f, t = filter_.split("/"), topic.split("/")
    for i, part in enumerate(f):
        if part == "#":
            return True
        if i >= len(t) or (part != "+" and part != t[i]):
            return False
    return len(f) == len(t)


class _Client:
    def __init__(self, sock):
        self.sock = sock
        self.filters = set()
        self.lock = threading.Lock()

    def send(self, data):
        try:
            with self.lock:
                self.sock.sendall(data)
            return True
        except OSError:
            return False


class MiniBroker:
    def __init__(self, host="127.0.0.1", port=0, log=None):
        self.host, self.port = host, port
        self.log = log or (lambda text: None)
        self.drop = None          # tests: function(topic, payload) -> True to silently lose a delivery
        self.delivered = 0
        self._clients = set()
        self._lock = threading.Lock()
        self._listener = None
        self._running = False

    def start(self):
        self._listener = socket.socket()
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind((self.host, self.port))
        self._listener.listen()
        self._listener.settimeout(0.2)
        self.port = self._listener.getsockname()[1]
        self._running = True
        threading.Thread(target=self._accept_loop, daemon=True).start()

    def stop(self):
        self._running = False
        with self._lock:
            clients = list(self._clients)
        for c in clients:
            try:
                c.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            c.sock.close()
        if self._listener:
            self._listener.close()

    def _accept_loop(self):
        while self._running:
            try:
                sock, addr = self._listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with self._lock:
                if len(self._clients) >= MAX_CLIENTS:
                    sock.close()
                    continue
            sock.settimeout(3.0)
            threading.Thread(target=self._serve, args=(sock, addr), daemon=True).start()

    def _serve(self, sock, addr):
        client = _Client(sock)
        buf = bytearray()
        connected = False
        deadline = time.monotonic() + 10   # must say CONNECT within 10 s
        try:
            while self._running:
                try:
                    chunk = sock.recv(65536)
                except socket.timeout:
                    if not connected and time.monotonic() > deadline:
                        break
                    continue
                if not chunk:
                    break
                buf += chunk
                while True:
                    packet = _take_packet(buf)
                    if packet is None:
                        break
                    first, body = packet
                    kind = first >> 4
                    if not connected:
                        if kind != 1:
                            return
                        connected = True
                        with self._lock:
                            self._clients.add(client)
                        client.send(b"\x20\x02\x00\x00")           # CONNACK: accepted
                        continue
                    if kind == 3:
                        self._on_publish(first, body, client)
                    elif kind == 8:                                 # SUBSCRIBE
                        pid = body[:2]
                        pos, codes = 2, b""
                        while pos < len(body):
                            (n,) = struct.unpack("!H", body[pos:pos + 2])
                            client.filters.add(body[pos + 2:pos + 2 + n].decode("utf-8", "replace"))
                            pos += 2 + n + 1
                            codes += b"\x00"
                        client.send(b"\x90" + _varint(2 + len(codes)) + pid + codes)
                    elif kind == 10:                                # UNSUBSCRIBE
                        pid = body[:2]
                        pos = 2
                        while pos < len(body):
                            (n,) = struct.unpack("!H", body[pos:pos + 2])
                            client.filters.discard(body[pos + 2:pos + 2 + n].decode("utf-8", "replace"))
                            pos += 2 + n
                        client.send(b"\xb0\x02" + pid)
                    elif kind == 12:                                # PINGREQ
                        client.send(b"\xd0\x00")
                    elif kind == 14:                                # DISCONNECT
                        return
        except (OSError, ValueError, struct.error):
            pass
        finally:
            with self._lock:
                self._clients.discard(client)
            try:
                sock.close()
            except OSError:
                pass

    def _on_publish(self, first, body, sender):
        qos = (first >> 1) & 3
        (n,) = struct.unpack("!H", body[:2])
        topic = body[2:2 + n].decode("utf-8", "replace")
        pos = 2 + n
        if qos:
            if qos == 1:
                sender.send(b"\x40\x02" + body[pos:pos + 2])
            pos += 2
        payload = body[pos:]
        packet_body = struct.pack("!H", n) + topic.encode("utf-8") + payload   # delivered at QoS 0
        packet = b"\x30" + _varint(len(packet_body)) + packet_body
        with self._lock:
            targets = list(self._clients)
        for client in targets:
            if any(_matches(f, topic) for f in list(client.filters)):
                if self.drop and self.drop(topic, payload):
                    continue
                if client.send(packet):
                    self.delivered += 1


def main():
    parser = argparse.ArgumentParser(description="A tiny MQTT broker for the UNO game's online rooms.")
    parser.add_argument("--host", default="0.0.0.0", help="address to listen on (default: all)")
    parser.add_argument("--port", type=int, default=1883)
    args = parser.parse_args()
    broker = MiniBroker(args.host, args.port, log=print)
    try:
        broker.start()
    except OSError as error:
        raise SystemExit(f"Could not listen on port {args.port}: {error}")
    print(f"Mini MQTT broker listening on {args.host}:{broker.port}. Press Ctrl+C to stop.", flush=True)
    try:
        while True:
            time.sleep(60)
            print(time.strftime("%H:%M:%S"), f"{len(broker._clients)} clients, {broker.delivered} messages delivered",
                  flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        broker.stop()


if __name__ == "__main__":
    main()
