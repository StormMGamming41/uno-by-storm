#!/usr/bin/env python3
"""
A UNO lobby that runs by itself, with no window and no player attached.

Put this on a computer that is always on and reachable from the internet (a cloud server,
a Raspberry Pi, a spare PC...) and everyone joins it by its address. Nobody has to host from
their own home. It needs only Python 3.8+ and these files: server.py, network.py, uno.py, relay.py.
(No pygame needed on the server.)

    python3 server.py                      # listen on port 5555, no lobby code
    python3 server.py --code mysecret      # require a lobby code to join
    python3 server.py --port 6000
    python3 server.py --online             # ALSO open an online room (a room code players can type)

--online is handy when the server sits behind a home router: friends join with the room code
and nobody needs to open a port. It needs relay.py next to the other files.

The first person to join is the lobby leader and can start games. If they leave, the next
person takes over. When everybody has left the lobby resets (scores included).
"""

import argparse
import os
import signal
import sys
import time

import relay
from network import DEFAULT_PORT, PROTOCOL_VERSION, Server


def main():
    parser = argparse.ArgumentParser(description="Run a dedicated UNO lobby.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help=f"TCP port to listen on (default {DEFAULT_PORT})")
    parser.add_argument("--code", default=os.environ.get("UNO_CODE", ""),
                        help="lobby code players must enter (or set the UNO_CODE variable)")
    parser.add_argument("--online", action="store_true",
                        help="also open an online room that friends can join with a room code")
    args = parser.parse_args()

    def log(text):
        print(time.strftime("%Y-%m-%d %H:%M:%S"), text, flush=True)

    server = Server(args.port, code=args.code, dedicated=True, log=log)
    try:
        server.start()
    except OSError as error:
        sys.exit(f"Could not listen on port {args.port}: {error}")

    log(f"UNO server (protocol {PROTOCOL_VERSION}) listening on port {args.port}")
    if not args.code:
        log("Note: no lobby code is set, so anyone who finds this address can join. "
            "Use --code to require one.")
    if args.online:
        server.start_relay()
    log("Press Ctrl+C to stop.")

    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))  # so service managers can stop it cleanly
    announced = ""
    try:
        while True:
            server.update()
            if args.online and server.room_code and server.room_code != announced:
                announced = server.room_code
                log(f"ONLINE ROOM CODE: {relay.format_code(announced)}  (friends choose the Room code tab)")
            time.sleep(0.02)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        server.close()


if __name__ == "__main__":
    main()
