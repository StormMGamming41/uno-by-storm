"""
A headless smoke test the PACKAGED game can run on itself:   UnoByStorm.exe --selftest

It checks that everything the game needs actually made it into the package (fonts, network,
settings), opens every screen, and plays the start of a real game between two players over
localhost. It needs no screen or sound (SDL's "dummy" drivers). The result is printed and written to
selftest_result.txt; the exit code is 0 only if every check passed. The cloud build runs this
on the freshly built exe.
"""

import os
import socket
import sys
import time
import traceback


def run(game_class):
    os.environ["SDL_VIDEODRIVER"] = "dummy"      # no window needed
    os.environ["SDL_AUDIODRIVER"] = "dummy"
    lines, failed = [], []

    def check(name, ok, extra=""):
        lines.append(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({extra})" if extra else ""))
        if not ok:
            failed.append(name)

    try:
        import pygame
        import clipboard
        import network
        import settings
        import ui_objects
        from viewport import view

        check("python / pygame", True, f"python {sys.version.split()[0]}, pygame {pygame.version.ver}")
        check("settings can be written and read", settings.save(selftest=1) and settings.get("selftest") == 1,
              settings.SETTINGS_FILE)
        font_found = os.path.exists(ui_objects.FONT_PATH)
        lines.append(f"info  pixel font {'found' if font_found else 'NOT found (default font used)'}: {ui_objects.FONT_PATH}")

        game = game_class()
        check("window and canvas", game.canvas is not None, f"canvas {view.size}, window {pygame.display.get_surface().get_size()}")

        def frames(n, dt=0.034):
            for _ in range(n):
                for event in pygame.event.get():
                    game.handle_event(event)
                game.step(dt)
                view.present()

        for name in ("menu", "mode_select", "host", "join", "help"):
            try:
                game.change_scene(name)
                frames(12)
                check(f"screen '{name}' draws", True)
            except Exception:
                check(f"screen '{name}' draws", False, traceback.format_exc().splitlines()[-1])

        try:
            clipboard.copy("selftest")
            clipboard.paste()
            check("clipboard calls do not crash", True)
        except Exception:
            check("clipboard calls do not crash", False, traceback.format_exc().splitlines()[-1])

        # a real two-player game over localhost
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        game.change_scene("host")
        frames(3)
        game.scene.online_box.checked = False
        game.scene.port_box.text = str(port)
        game.scene.start()
        frames(5)
        bot = network.Client()
        bot.connect("127.0.0.1", port, name="Bot")
        for _ in range(100):
            frames(1)
            bot.update()
            time.sleep(0.02)
            if type(game.scene).__name__ == "LobbyScene":
                break
        check("host lobby opens", type(game.scene).__name__ == "LobbyScene", type(game.scene).__name__)
        game.client.send({"type": "start"})
        for _ in range(150):
            frames(1)
            bot.update()
            time.sleep(0.01)
        check("game starts and the table draws", type(game.scene).__name__ == "GameScene", type(game.scene).__name__)
        check("both players were dealt cards", bool(game.client.game) and len(game.client.game["hand"]) == 7)
        game.disconnect()
    except Exception:
        check("self-test ran to the end", False, traceback.format_exc().splitlines()[-1])
        lines.append(traceback.format_exc())

    text = "\n".join(lines) + f"\n\n{'ALL CHECKS PASSED' if not failed else 'FAILED: ' + ', '.join(failed)}\n"
    print(text)
    try:
        with open("selftest_result.txt", "w", encoding="utf-8") as f:
            f.write(text)
    except OSError:
        pass
    return 0 if not failed else 1
