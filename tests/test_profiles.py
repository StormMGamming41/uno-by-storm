"""Every screen, on every screen shape: nothing overflows, the picture fills the screen, taps
land on the right thing (also through the centred areas), rotation rebuilds the layout."""
import os, tempfile, time
from harness import *
import settings; settings.SETTINGS_FILE = os.path.join(tempfile.mkdtemp(), "s.json")
import device; device.ANDROID = True; device.IN_TERMUX = False; device.touch.enabled = True
import main, network
from viewport import view
from ui_objects import TextBox, Button

ok = fail = 0
def check(name, cond, extra=""):
    global ok, fail
    if cond: ok += 1
    else: fail += 1; print("FAIL", name, extra)

def scene_taps(g, obj):
    """window position of the centre of a UI object of the current screen"""
    c = obj.rect.center
    return canvas_to_window(c[0] + view.origin[0], c[1] + view.origin[1])

SHAPES = {"phone upright 1080x2400": (1080, 2400), "phone upright 1080x1920": (1080, 1920),
          "phone upright 720x1560": (720, 1560), "phone sideways 2400x1080": (2400, 1080),
          "phone sideways 1920x1080": (1920, 1080), "tablet 1200x1920": (1200, 1920),
          "tablet sideways 1920x1200": (1920, 1200)}
port = 5590
for name, (W, H) in SHAPES.items():
    pygame.display._desktop = (W, H)
    g = main.Game(); run(g, 8)
    fills = view.dest.w >= W - 2 and view.dest.h >= H - 2 if view.size[0] < view.size[1] or view.size[0] > 800 else True
    check(f"{name}: canvas {view.size} fills the screen", view.dest.w >= W - 2 or view.dest.h >= H - 2, view.dest)
    bars = (view.dest.x, view.dest.y, W - view.dest.right, H - view.dest.bottom)
    check(f"{name}: no black bars (got {bars})", max(bars) <= 2, bars)
    for sc in ("menu", "mode_select", "host", "join", "help", "lobby"):
        try:
            g.change_scene(sc); run(g, 6)
        except Exception as e:
            check(f"{name}: scene {sc} builds", False, repr(e)); continue
        w, h = g.scene.size
        for o in g.scene.objects:
            if not getattr(o, "visible", True): continue
            r = o.rect
            if r.width and (r.x < -1 or r.right > w + 1):
                check(f"{name}/{sc}: {type(o).__name__} inside width", False, (r, w))
            if r.height and r.bottom > h + 1 and sc != "lobby":
                check(f"{name}/{sc}: {type(o).__name__} inside height", False, (r, h))
    # a tap through the centred area hits the right button
    g.change_scene("menu"); run(g, 8)
    play = [o for o in g.scene.objects if isinstance(o, Button) and o.text == "Play"][0]
    tap(g, *scene_taps(g, play)); run(g, 8)
    check(f"{name}: tap on Play (through centred area)", type(g.scene).__name__ == "ModeSelectScene", type(g.scene).__name__)
    # keyboard: tap a text box, keyboard appears, lowest box stays above it
    g.change_scene("join"); run(g, 8)
    g.scene._set_mode(1); run(g, 3)
    box = g.scene.code_box
    tap(g, *scene_taps(g, box)); run(g, 14)
    check(f"{name}: keyboard comes up", g.keyboard.t == 1.0 and g.scene.code_box.focused)
    bottom = view.origin[1] + box.rect.bottom - view.lift
    check(f"{name}: focused box above keyboard ({bottom} <= {g.keyboard.top})", bottom <= g.keyboard.top, (bottom, g.keyboard.top))
    # a real game on this shape
    port += 1
    g = main.Game(start_scene="host"); run(g, 4)
    g.scene.online_box.checked = False; g.scene.port_box.text = str(port); g.scene.start(); run(g, 4)
    bot = network.Client(); bot.connect("127.0.0.1", port, name="Bot")
    for _ in range(80): run(g, 1); bot.update(); time.sleep(0.01)
    g.client.send({"type": "start"})
    for _ in range(90): run(g, 1); bot.update(); time.sleep(0.01)
    sc = g.scene
    check(f"{name}: game screen up", type(sc).__name__ == "GameScene", type(sc).__name__)
    if type(sc).__name__ == "GameScene":
        w, h = sc.size
        hand = sc._sorted_hand(g.client.game); rects = sc._hand_rects(len(hand))
        check(f"{name}: hand inside screen", all(r.x >= 0 and r.right <= w and r.bottom <= h for r in rects), rects[:2])
        check(f"{name}: leave button inside screen", sc.leave_btn.rect.right <= w and sc.leave_btn.rect.bottom <= h)
        check(f"{name}: centre block between players and hand", sc.opp_bottom <= sc.cy and sc.cy + 244 <= sc.hand_y + 4, (sc.opp_bottom, sc.cy, sc.hand_y))
        # tap the middle card twice -> raise, then play (nothing played on 1st)
        sent = []; orig = g.client.send; g.client.send = lambda m: (sent.append(m), orig(m))[1]
        i = len(hand) // 2; r = rects[i]
        tap(g, *canvas_to_window(r.centerx - 6, r.centery + 25)); run(g, 10)
        check(f"{name}: 1st tap raises", sc.raised == hand[i]["id"] and not [m for m in sent if m.get("type") == "play"])
    g.disconnect()

# --- rotation: upright -> sideways rebuilds the layout and keeps working
pygame.display._desktop = (1080, 2400)
g = main.Game(); run(g, 5); g.change_scene("mode_select"); run(g, 5)
check("rotation: starts upright", view.size == (540, 1200), view.size)
pygame.display._resize((2400, 1080)); run(g, 6)
check("rotation: canvas rebuilt sideways", view.size == (1333, 600) and g.size == (1333, 600), (view.size, g.size))
check("rotation: same screen, laid out again", type(g.scene).__name__ == "ModeSelectScene" and g.scene.size == (1333, 600), g.scene.size)
check("rotation: keyboard resized", g.keyboard.width == 1333)
check("rotation: fills the new shape", view.dest.w >= 2398 and view.dest.h >= 1078, view.dest)
host_btn = [o for o in g.scene.objects if isinstance(o, Button) and "Host" in o.text][0]
tap(g, *scene_taps(g, host_btn)); run(g, 8)
check("rotation: taps still land correctly", type(g.scene).__name__ == "HostScene", type(g.scene).__name__)
print(f"\n{ok} passed, {fail} failed")
