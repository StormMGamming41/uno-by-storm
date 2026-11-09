#!/usr/bin/env python3
"""
Checks whether the game's "online rooms" can work from THIS computer and internet connection.

    python check_online.py                       # checks the relay servers the game uses
    python check_online.py --broker my.host:1883 # checks one you name (add :tls for TLS)

For each relay server it connects, sends an encrypted test message to itself and waits for it
to come back, and reports how long that took. The game uses the first server on the list that
works, so you only need ONE line to say OK. Nothing is stored and no game is started.
"""

import argparse
import secrets
import sys
import threading
import time

import relay


def check_broker(broker, timeout=8.0):
    """-> (ok, message). Never raises."""
    host, port, tls = broker
    sender = receiver = None
    try:
        started = time.perf_counter()
        sender = relay.MqttClient(host, port, tls)
        sender.connect(timeout=timeout)
        connect_ms = (time.perf_counter() - started) * 1000

        keys = relay.RoomKeys(relay.new_room_code(0))        # same encryption the game uses
        topic = keys.down_topic("selftest" + secrets.token_hex(3))
        arrived, result = threading.Event(), []

        def on_message(t, payload):
            result.append(keys.open(payload))
            arrived.set()

        receiver = relay.MqttClient(host, port, tls)
        receiver.on_message = on_message
        receiver.connect(timeout=timeout)
        receiver.subscribe(topic, timeout=timeout)

        sent_at = time.perf_counter()
        sender.publish(topic, keys.seal({"f": "h", "n": 1, "m": {"type": "ping", "t": 1}}))
        if not arrived.wait(timeout):
            return False, "connected, but the test message never came back (the server may be dropping messages)"
        round_trip_ms = (time.perf_counter() - sent_at) * 1000
        if not result or not result[0] or result[0].get("m", {}).get("type") != "ping":
            return False, "a message came back but it was damaged"
        return True, f"works. connect {connect_ms:.0f} ms, message round trip {round_trip_ms:.0f} ms"
    except relay.MqttError as error:
        return False, f"cannot use it: {error}"
    except Exception as error:   # a diagnostic must never crash
        return False, f"unexpected problem: {error.__class__.__name__}: {error}"
    finally:
        for client in (sender, receiver):
            if client:
                client.close()


def parse_broker(text):
    parts = text.split(":")
    host = parts[0]
    port = int(parts[1]) if len(parts) > 1 and parts[1] else 1883
    return host, port, len(parts) > 2 and parts[2].lower() == "tls"


def main():
    parser = argparse.ArgumentParser(description="Check whether the game's online rooms can work here.")
    parser.add_argument("--broker", action="append", help="host[:port[:tls]] to check instead of the built-in list")
    args = parser.parse_args()
    brokers = [parse_broker(b) for b in args.broker] if args.broker else relay.load_brokers()

    print(f"Checking {len(brokers)} relay server(s)...\n")
    working = []
    for index, broker in enumerate(brokers):
        ok, message = check_broker(broker)
        print(f"  [{'OK ' if ok else 'FAIL'}] {broker[0]}:{broker[1]}  {message}")
        if ok:
            working.append(index)
    print()
    if working:
        first = working[0]
        print(f"Online rooms should work from here. The game will use #{first + 1} "
              f"({brokers[first][0]}) when it is the first one to answer.")
        if first != 0:
            print("Note: earlier servers on the list failed, so rooms will be a little slower to open.")
        return 0
    print("Online rooms will NOT work from this connection right now.")
    print("Possible reasons: no internet, a firewall or school/work network blocking port 1883,")
    print("or all the free public servers being down. You can run your own relay server with")
    print("mini_broker.py (see README_INTERNET.md), or use one of the other ways to play online.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
