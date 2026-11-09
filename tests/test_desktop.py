"""PC: fixed window sizes (no dragging), F4 cycles them, taps map correctly in each."""
import os, tempfile
from harness import *
import settings; settings.SETTINGS_FILE = os.path.join(tempfile.mkdtemp(), "s.json")
import device; device.ANDROID = False; device.IN_TERMUX = False
pygame.display._desktop = (1920, 1080)
import main
from viewport import view
from scenes import ModeSelectScene
ok = 0
def check(name, cond, extra=""):
    global ok
    assert cond, (name, extra); ok += 1; print("PASS", name)

g = main.Game(); run(g, 5)
check("window is NOT resizable", not (pygame.display.flags & pygame.RESIZABLE), pygame.display.flags)
check("canvas stays 800x600", view.size == (800, 600))
check("default = biggest fixed size that fits (1.5x = 1200x900)", pygame.display.get_surface().get_size() == (1200, 900), pygame.display.get_surface().get_size())
check("fills the window exactly", view.dest.size == (1200, 900) and view.dest.topleft == (0, 0))
check("60 fps on a PC", main.FPS == 60)
tap(g, *canvas_to_window(400, 320)); run(g, 8)
check("click maps correctly at 1.5x", isinstance(g.scene, ModeSelectScene))
g.change_scene("menu"); run(g, 5)
g.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F4, unicode="")); run(g, 3)
check("F4 -> next fixed size (800x600)", pygame.display.get_surface().get_size() == (800, 600), pygame.display.get_surface().get_size())
tap(g, *canvas_to_window(400, 320)); run(g, 8)
check("click maps correctly at 1x", isinstance(g.scene, ModeSelectScene))
g.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F4, unicode="")); run(g, 3)
check("F4 cycles back to 1200x900", pygame.display.get_surface().get_size() == (1200, 900))
# a small laptop screen only offers the small window
pygame.display._desktop = (1366, 768); view.desktop = (1366, 768)
import viewport
check("1366x768 desktop: only 800x600 fits", viewport.desktop_window_sizes(1366, 768) == [1.0])
g.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F3, unicode="")); check("F3 toggles touch mode", device.touch.enabled)
print(f"\n{ok} passed")
