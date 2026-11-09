"""present(): idle frames send nothing, moving frames send only changed rows, and once things
settle the screen is IDENTICAL to a full scale of the canvas (no seams left behind)."""
import os, tempfile, time
from harness import *
import settings; settings.SETTINGS_FILE = os.path.join(tempfile.mkdtemp(), "s.json")
import device
device.ANDROID = True; device.touch.enabled = True
pygame.display._desktop = (2400, 1080)          # a typical phone's native size
import main, network
from PIL import ImageChops
from viewport import view, CANVAS_SIZE
from scenes import GameScene

ok = fail = 0
def check(name, cond, extra=""):
    global ok, fail
    if cond: ok += 1; print("PASS", name)
    else: fail += 1; print("FAIL", name, extra)

def expected_screen():
    """What a full-frame scale of the current canvas looks like in the window."""
    from PIL import Image
    win = Image.new("RGB", pygame.display._screen.size, (0, 0, 0))
    scaler = pygame.transform.smoothscale if view.smooth else pygame.transform.scale
    pic = scaler(view.canvas, view.dest.size)
    win.paste(pic._img.convert("RGB"), view.dest.topleft)
    return win

def diff_share(a, b):
    d = ImageChops.difference(a, b).convert("L").point(lambda v: 255 if v > 24 else 0)
    return sum(1 for v in d.tobytes() if v) / (a.width * a.height)

def sent():
    return [e for e in pygame.display.log if e == "flip" or (isinstance(e, tuple) and e[0] == "update")]

g = main.Game(start_scene="mode_select"); view.auto_scale = False; run(g, 12)   # no auto-switch: the stand-in is slow
check("native-size window", pygame.display._window.get_size() == (2400, 1080), pygame.display._window.get_size())
check("canvas matches the screen's shape (1333x600)", view.size == (1333, 600), view.size)
check("picture fills the screen: no black bars", view.dest.x <= 1 and view.dest.w >= 2398 and view.dest.h == 1080, view.dest)
check("keyboard is as wide as the canvas", g.keyboard.width == 1333)
pygame.display.log.clear(); run(g, 20)
check("idle screen: nothing sent for 20 frames", sent() == [], sent()[:3])
check("idle frames counted as skipped", view.stats["skipped"] >= 20)

# the Quit-button hover animation / a changing label = a small change -> partial update
pygame.display.log.clear()
g.scene.message.text = "Something changed down here."
run(g, 1)
ups = sent()
check("one small change -> one partial update", len(ups) == 1 and ups[0][0] == "update" and ups[0][1][3] < view.dest.h, ups)
check("partial rect lies inside the picture", pygame.Rect(ups[0][1]).clip(view.dest) == pygame.Rect(ups[0][1]))
run(g, 20)                                                   # quiet again -> one cleanup repaint
full = [e for e in sent() if e == ("update", view.dest.as_tuple())]
check("one full repaint after it goes quiet", len(full) == 1, sent())
check("screen identical to a full scale (no seams)", diff_share(pygame.display._screen, expected_screen()) == 0.0 and
      ImageChops.difference(pygame.display._screen, expected_screen()).getbbox() is None)

# a real game: cards flying
g.disconnect(); g = main.Game(start_scene="host"); view.auto_scale = False; run(g, 5)
g.scene.online_box.checked = False; g.scene.port_box.text = "5598"; g.scene.start(); run(g, 5)
bot = network.Client(); bot.connect("127.0.0.1", 5598, name="Bot")
for _ in range(80):
    run(g, 1); bot.update(); time.sleep(0.02)
g.client.send({"type": "start"})
mid_frames = []; fly = {"frames": 0, "rows": 0}
before = dict(view.stats)
for _ in range(120):
    r0 = view.stats["rows_sent"]
    run(g, 1, dt=0.034); bot.update(); time.sleep(0.01)
    if isinstance(g.scene, GameScene) and g.scene.flights:
        fly["frames"] += 1; fly["rows"] += view.stats["rows_sent"] - r0
    if not (isinstance(g.scene, GameScene) and not g.scene.hidden and not g.scene.flights):
        mid_frames.append(diff_share(pygame.display._screen, expected_screen()))
st = {k: view.stats[k] - before[k] for k in before}
total_rows = st["frames"] * CANVAS_SIZE[1]
print("game start-up, %d frames: %s -> rows sent %d%% of 'full every frame'" % (st["frames"], st, 100 * st["rows_sent"] // total_rows))
if fly["frames"]:
    print("  frames with cards in the air: %d, average %d%% of the picture's rows sent per frame" % (fly["frames"], 100 * fly["rows"] // (fly["frames"] * CANVAS_SIZE[1])))
check("sends far less than a full picture every frame", st["rows_sent"] < 0.5 * total_rows, st)
if mid_frames:
    print("  while cards moved, share of pixels differing from a full redraw: max %.2f%%" % (100 * max(mid_frames)))
    check("partial updates look right while moving (<1% pixels differ)", max(mid_frames) < 0.01, max(mid_frames))
run(g, 25)
check("settled game: screen identical to full scale", ImageChops.difference(pygame.display._screen, expected_screen()).getbbox() is None)
check("no display errors survived", view.errors == 0, view.events[-3:])
print(f"\n{ok} passed, {fail} failed"); g.disconnect()
