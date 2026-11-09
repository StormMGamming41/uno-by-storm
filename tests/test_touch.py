import os, tempfile, json
from harness import *
import settings
settings.SETTINGS_FILE = os.path.join(tempfile.mkdtemp(), "settings.json")
import device
device.ANDROID = True; device.touch.enabled = True
import main
from viewport import view
from scenes import JoinScene
from theme import theme

CX = lambda: view.size[0] // 2          # the canvas is wider than 800 on a wide screen
ok = fail = 0
def check(name, cond, extra=""):
    global ok, fail
    if cond: ok += 1; print("PASS", name)
    else: fail += 1; print("FAIL", name, extra)

def ctap(g, x, y):               # tap at CANVAS coordinates (maps to window first)
    tap(g, *canvas_to_window(x, y))

g = main.Game(); run(g, 10)
# 1. mapping: tap Play (canvas 400,320) through the scaled window
ctap(g, CX(), 320); run(g, 10)
check("tap Play -> mode_select", type(g.scene).__name__ == "ModeSelectScene", type(g.scene).__name__)
# tap on the black bar must do nothing
before = type(g.scene).__name__
tap(g, 20, 300); run(g, 3)
check("tap on black bar ignored", type(g.scene).__name__ == before)
ctap(g, CX(), 335); run(g, 10)                      # Join Game
check("tap Join -> join scene", isinstance(g.scene, JoinScene))
check("autofocused box does not pop keyboard", g.keyboard.t == 0 and view.lift == 0)

# 2. keyboard appears on tapping the name box, lifts nothing for the name box (y<=226)
ctap(g, CX(), 200); run(g, 12)
check("keyboard up after tapping box", g.keyboard.t == 1.0 and g.kb_armed)
shot("join_keyboard_room")

def key_center(label, symbols=None):
    if symbols is not None: g.keyboard.symbols = symbols
    for face, (lab, kind) in g.keyboard._pages[g.keyboard.symbols]:
        if lab == label: return face.center
    raise KeyError(label)

def press(label):
    x, y = key_center(label); ctap(g, x, y)

press("a"); press("b")
check("typed 'ab'", g.scene.name_box.text == "ab", g.scene.name_box.text)
press("Shift"); press("c")
check("shift gives one capital", g.scene.name_box.text == "abC", g.scene.name_box.text)
press("c")
check("shift turns off after one letter", g.scene.name_box.text == "abCc")
press("Del"); press("Del")
check("backspace", g.scene.name_box.text == "ab")
# hold backspace -> repeats
x, y = key_center("Del"); wx, wy = canvas_to_window(x, y)
pygame.mouse.pos = (wx, wy)
pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(wx, wy), button=1))
g.scene.name_box.text = "abcdefghij"
run(g, 30)                                           # ~1 s held
pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONUP, pos=(wx, wy), button=1)); run(g, 2)
check("holding backspace repeats", len(g.scene.name_box.text) < 6, g.scene.name_box.text)

# 3. Go moves to the room box (stays armed), then address tab needs lift
press("Go"); run(g, 3)
check("Go moved focus to room box, keyboard stays", g.scene.room_box.focused and g.keyboard.t == 1.0)
ctap(g, CX() + 80, 116); run(g, 3)                         # 'Address' tab (x 400..550, y 96..136 scene)
check("address tab selected", g.scene.tabs.selected == 1)
ctap(g, CX(), 291); run(g, 3); ctap(g, CX(), 291)      # no-op taps on the address box: focus it
g.scene.address_box.focused = True; g.kb_armed = True
ctap(g, CX(), 291); run(g, 12)                         # tap on address box again
check("address box focused + keyboard", g.scene.address_box.focused and g.keyboard.t == 1.0)
g.scene.code_box.focused = False
# focus the lobby code box (lowest, bottom 406) and check lift
g.scene.address_box.focused = False; g.scene.code_box.focused = True; run(g, 15)
check("lift keeps lowest box above keyboard", view.lift > 0 and g.scene.code_box.rect.bottom - view.lift <= g.keyboard.top, view.lift)
shot("join_address_lifted")
# a tap on the lifted code box lands on the code box (scene coords)
ctap(g, CX(), 356 + 25 - int(view.lift)); run(g, 2)
check("tap on lifted box hits it", g.scene.code_box.focused)

# 4. symbols page: ':' and '/' reach the address box
g.scene.code_box.focused = False; g.scene.address_box.focused = True; run(g, 3)
press("?123")
for ch in "192.168.0.5:5555":
    if ch in ":": press(ch)
    else: press(ch)
check("address typed with ':' ", g.scene.address_box.text == "192.168.0.5:5555", g.scene.address_box.text)
press("/")
check("'/' accepted by address box", g.scene.address_box.text.endswith("/"))
shot("join_symbols")
# letters page: greyed keys for boxes that reject them
g.scene.address_box.focused = False; g.scene.name_box.focused = True
# 5. Hide key
press("abc"); press("Hide"); run(g, 12)
check("Hide puts keyboard away", g.keyboard.t == 0.0 and view.lift == 0)
# tap on a box brings it back, tap elsewhere hides
ctap(g, CX(), 200); run(g, 12)
check("tap box again -> keyboard", g.keyboard.t == 1.0)
ctap(g, CX() + 300, 150); run(g, 12)
check("tap elsewhere -> hidden", g.keyboard.t == 0.0)

# 6. settings: theme + touch do not erase each other
theme.set("dark"); device.touch.set(False); theme.set("light")
data = json.load(open(settings.SETTINGS_FILE))
check("settings keep both keys", data == {"theme": "light", "touch": False}, data)
settings.save(other=1); theme.set("dark")
check("unknown keys survive", json.load(open(settings.SETTINGS_FILE)).get("other") == 1)
open(settings.SETTINGS_FILE, "w").write("{not json")
check("corrupt file tolerated", settings.load() == {})
# 7. only the picture area is re-sent (never the black bars)
pygame.display.log.clear(); device.touch.set(True); run(g, 3); g.scene.name_box.text = "x"; run(g, 3)
ups = [e for e in pygame.display.log if isinstance(e, tuple)]
inside = all(pygame.Rect(e[1]).clip(view.dest) == pygame.Rect(e[1]) for e in ups)
check("present() sends only inside the picture rect", inside and "flip" not in pygame.display.log, pygame.display.log[:3])
print(f"\n{ok} passed, {fail} failed")
