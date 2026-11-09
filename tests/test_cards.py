"""Tap-to-raise in a REAL game: host + one bot over localhost TCP, touch mode on."""
import os, tempfile, time
from harness import *
import settings
settings.SETTINGS_FILE = os.path.join(tempfile.mkdtemp(), "s.json")
import device
device.ANDROID = True; device.touch.enabled = True
import main, network
from viewport import view
from scenes import GameScene, HostScene

ok = fail = 0
def check(name, cond, extra=""):
    global ok, fail
    if cond: ok += 1; print("PASS", name)
    else: fail += 1; print("FAIL", name, extra)

g = main.Game(start_scene="host"); run(g, 5)
g.scene.online_box.checked = False
g.scene.port_box.text = "0" if False else "5599"
g.scene.start(); run(g, 5)
bot = network.Client(); bot.connect("127.0.0.1", 5599, name="Bot")
for _ in range(80):
    run(g, 1); bot.update(); time.sleep(0.02)
check("bot joined lobby", type(g.scene).__name__ == "LobbyScene", type(g.scene).__name__)
g.client.send({"type": "start"})
for _ in range(150):
    run(g, 1); bot.update(); time.sleep(0.02)
    if isinstance(g.scene, GameScene) and not g.scene.hidden and not g.scene.flights: break
check("game started", isinstance(g.scene, GameScene), type(g.scene).__name__)
sc = g.scene; run(g, 40)
hand = sc._sorted_hand(g.client.game)
print("hand size", len(hand), "my turn", sc._my_turn(g.client.game))
shot("game_touch_before")
rects = sc._hand_rects(len(hand))
sent = []
orig = g.client.send
g.client.send = lambda m: (sent.append(m), orig(m))[1]

# tap the middle card (overlapped): first tap raises, sends nothing
mid = len(hand) // 2
x, y = rects[mid].centerx - 8, rects[mid].centery + 20
tap(g, *canvas_to_window(x, y)); run(g, 20)
check("1st tap raises that card", sc.raised == hand[mid]["id"] and sc.hover_i == mid, (sc.raised, sc.hover_i))
check("1st tap plays nothing", not [m for m in sent if m.get("type") == "play"], sent)
shot("game_touch_raised")
# tap elsewhere lowers it
tap(g, *canvas_to_window(50, 420)); run(g, 5)
check("tap elsewhere lowers card", sc.raised is None)
# raise, then tap a different card -> moves the raise
tap(g, *canvas_to_window(x, y)); run(g, 5)
other = 1
tap(g, *canvas_to_window(rects[other].x + 6, rects[other].centery + 20)); run(g, 5)
check("tap another card moves the raise", sc.raised == hand[other]["id"], sc.raised)
# raise a playable card and tap again -> play message
g2 = g.client.game
play_ids = [c["id"] for c in hand if c["id"] in g2["playable"]]
tap(g, *canvas_to_window(50, 420)); run(g, 5)   # put any raised card back first
sent.clear()
if sc._my_turn(g2) and play_ids:
    i = [c["id"] for c in hand].index(play_ids[0])
    r = rects[i]; px, py = r.centerx, r.centery + 20
    # find a point where this card is the rightmost-covering one
    for dx in range(r.width - 4, 0, -2):
        if sc._card_at((r.x + dx, py), len(hand)) == i: px = r.x + dx; break
    tap(g, *canvas_to_window(px, py)); run(g, 20)
    check("playable card raised on 1st tap", sc.raised == play_ids[0], dict(i=i, px=px, py=py, at=sc._card_at((px,py), len(hand)), raised=sc.raised, want=play_ids[0], ids=[c["id"] for c in hand], lift=sc.lift))
    n0 = len([m for m in sent if m.get("type") == "play"])
    tap(g, *canvas_to_window(px, py - 10)); run(g, 5)
    plays = [m for m in sent if m.get("type") == "play"]
    check("2nd tap plays it", len(plays) == n0 + 1 or sc.pending_wild is not None, sent[-3:])
else:
    print("(not my turn / nothing playable in this random deal: play step skipped)")
print(f"\n{ok} passed, {fail} failed")
g.disconnect()
