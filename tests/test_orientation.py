"""
The Android problems reported on real phones, reproduced as far as a stand-in can:
  * the window changes size while the game is starting (the phone is still rotating)
  * the window surface is replaced behind our back (same size, or a new size): using the old
    one is an error (the stand-in raises 'display Surface quit' for it)
  * the window reports a tiny size for a moment during a rotation
  * the window flips between upright and sideways over and over, mid-game
  * window and display disagree about the orientation at start-up
Every case must end with: no exception, a layout that matches the window, a picture that fills the
screen, and a tap that lands on the right button.
"""
import os, tempfile, time
from harness import *
import settings; settings.SETTINGS_FILE = os.path.join(tempfile.mkdtemp(), "s.json")
import device; device.ANDROID = True; device.IN_TERMUX = False; device.touch.enabled = True
import viewport, main, network
from viewport import view, choose_canvas
from ui_objects import Button

ok = fail = 0
def check(name, cond, extra=""):
    global ok, fail
    if cond: ok += 1; print("PASS", name)
    else: fail += 1; print("FAIL", name, extra)

def consistent(label, W, H):
    """layout matches the window the phone really has, and fills it"""
    live = pygame.display.get_surface()
    check(f"{label}: window is {W}x{H}", live.get_size() == (W, H), live.get_size())
    check(f"{label}: canvas shaped for it {choose_canvas(W, H)}", view.size == choose_canvas(W, H), view.size)
    check(f"{label}: game and viewport agree", main_game.size == view.size and main_game.canvas is view.canvas)
    check(f"{label}: picture fills the screen", view.dest.w >= W - 2 and view.dest.h >= H - 2 or
          (view.dest.w >= W - 2 or view.dest.h >= H - 2) and max(view.dest.x, view.dest.y) <= 2, view.dest)
    check(f"{label}: layout belongs to the live surface", view._seen is live and view.ready)
    btns = [o for o in main_game.scene.objects if isinstance(o, Button) and o.text == "Play"]
    if btns:
        c = btns[0].rect.center
        tap(main_game, *canvas_to_window(c[0] + view.origin[0], c[1] + view.origin[1])); run(main_game, 8)
        check(f"{label}: tap on Play lands", type(main_game.scene).__name__ == "ModeSelectScene", type(main_game.scene).__name__)
        main_game.change_scene("menu"); run(main_game, 6)

def fresh(W, H):
    pygame.display._desktop = (W, H); pygame.display._reported_desktop = None
    pygame.display._window = None
    return main.Game()

# 1. rotation arrives in the middle of start-up (during the wait for the screen to settle)
pygame.display._desktop = (1080, 2400); pygame.display._window = None
calls = {"n": 0}
def rotate_during_startup():
    calls["n"] += 1
    if calls["n"] == 2:
        pygame.display._resize((2400, 1080))
pygame.event.on_pump = rotate_during_startup
main_game = main.Game(); del pygame.event.on_pump
run(main_game, 10)
check("1. start-up wait saw the rotation: no rebuild was needed", view.size == (1333, 600), view.size)
consistent("1. rotated during start-up", 2400, 1080)

# 2. same-size surface replaced behind our back (app switch / rotate and back)
for i in range(3):
    pygame.display._replace_surface(); run(main_game, 4)
check("2. survived 3 replaced surfaces", view.errors == 0 and view.ready, (view.errors, view.events[-2:]))
consistent("2. after replaced surfaces", 2400, 1080)

# 3. rotation to upright, mid-game scene; then a size of (1,1) for a moment, then sideways again
main_game.change_scene("mode_select"); run(main_game, 5)
pygame.display._resize((1080, 2400)); run(main_game, 4)
check("3. rotated upright: canvas rebuilt", view.size == (540, 1200) and main_game.scene.size[0] == 540, (view.size, main_game.scene.size))
pygame.display._resize((1, 1)); run(main_game, 5)
check("3. a (1,1) window is waited out, not drawn into", not view.ready)
pygame.display._resize((2400, 1080)); run(main_game, 5)
main_game.change_scene("menu"); run(main_game, 5)
consistent("3. back sideways", 2400, 1080)

# 4. flapping upright/sideways every few frames, with a real game running
port = 5560
main_game.disconnect(); main_game = fresh(1080, 2400); run(main_game, 4)
main_game.change_scene("host"); run(main_game, 4)
main_game.scene.online_box.checked = False; main_game.scene.port_box.text = str(port); main_game.scene.start(); run(main_game, 4)
bot = network.Client(); bot.connect("127.0.0.1", port, name="Bot")
for _ in range(80): run(main_game, 1); bot.update(); time.sleep(0.01)
main_game.client.send({"type": "start"})
for _ in range(60): run(main_game, 1); bot.update(); time.sleep(0.01)
shapes = [(2400, 1080), (1080, 2400)] * 6
errors = 0
for sh in shapes:
    pygame.display._resize(sh)
    try:
        run(main_game, 3); bot.update()
    except Exception as e:
        errors += 1; print("   exception while flapping:", repr(e))
check("4. flapped 12 times mid-game with no exception", errors == 0)
check("4. still in the game, state intact", type(main_game.scene).__name__ == "GameScene" and len(main_game.client.game["hand"]) == 7, type(main_game.scene).__name__)
W, H = shapes[-1]
check("4. game table laid out for the final shape", main_game.scene.size == choose_canvas(W, H) == view.size, (main_game.scene.size, view.size))
check("4. no display errors", view.errors == 0, view.events[-3:])
main_game.disconnect()

# 5. window and display disagree about the orientation at start-up: one retry, then consistent
pygame.display._window = None
pygame.display._desktop = (2400, 1080)
orig_set_mode = pygame.display.set_mode
count = {"n": 0}
def flaky_set_mode(size=(0, 0), flags=0, *a, **k):
    count["n"] += 1
    if count["n"] == 1 and tuple(size) == (0, 0):          # first window comes up the wrong way round
        pygame.display._desktop = (1080, 2400); r = orig_set_mode(size, flags); pygame.display._desktop = (2400, 1080)
        pygame.display._reported_desktop = (2400, 1080)
        return r
    pygame.display._reported_desktop = None
    return orig_set_mode(size, flags)
pygame.display.set_mode = flaky_set_mode
main_game = main.Game(); pygame.display.set_mode = orig_set_mode; run(main_game, 6)
check("5. disagreement detected and the window recreated", count["n"] == 2 and any("disagree" in e for e in view.events), (count, view.events[-4:]))
consistent("5. after the retry", 2400, 1080)

# 6. nothing usable at all at start-up: falls back instead of crashing
pygame.display._window = None; pygame.display._desktop = (50, 50)
try:
    main_game = main.Game(); run(main_game, 5); crashed = False
except Exception as e:
    crashed = repr(e)
check("6. a useless first window does not crash start-up", not crashed, crashed)
check("6. and the game ends up on a usable window", view.ready and view.canvas is not None)

# 7. a display error inside present() is survived, not fatal
pygame.display._desktop = (2400, 1080); pygame.display._window = None
main_game = main.Game(); run(main_game, 5)
real_flip, real_update = pygame.display.flip, pygame.display.update; boom = {"n": 0}
def bad(real):
    def wrapper(*a, **k):
        boom["n"] += 1
        if boom["n"] <= 3: raise pygame.error("simulated: surface lost")
        return real(*a, **k)
    return wrapper
pygame.display.flip, pygame.display.update = bad(real_flip), bad(real_update)
main_game.change_scene("mode_select")
try:
    run(main_game, 14); err = None
except Exception as e:
    err = repr(e)
pygame.display.flip, pygame.display.update = real_flip, real_update; run(main_game, 5)
check("7. display errors inside present() do not crash the game", err is None, err)
check("7. they were counted and the screen recovered", view.errors >= 1 and view.ready, (view.errors, view.events[-3:]))
print(f"\n{ok} passed, {fail} failed")
