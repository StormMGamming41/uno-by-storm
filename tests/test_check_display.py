"""Drive check_display.py with scripted taps (a 'good' run and a 'broken mapping' run)."""
import os, sys, tempfile, threading
from harness import *
import settings
settings.SETTINGS_FILE = os.path.join(tempfile.mkdtemp(), "s.json")
import device; device.ANDROID = False
import check_display as cd
from viewport import view
import keyboard

def scripted(offset=(0, 0)):
    """Feed events from inside the loop by wrapping pygame.event.get."""
    state = {"n": 0, "keys": []}
    real_get = pygame.event.get
    plan = []
    def at(x, y):   # canvas -> window pos (optionally with a deliberate error)
        wx, wy = canvas_to_window(x, y)
        return (wx + offset[0], wy + offset[1])
    def get():
        state["n"] += 1; n = state["n"]
        if n == 3:
            for (x, y) in cd.TARGETS:
                p = at(x, y)
                pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=p, button=1))
                pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONUP, pos=p, button=1))
            p = at(400, 355)
            pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=p, button=1))
            pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONUP, pos=p, button=1))
        if n >= 20 and n % 4 == 0 and state["keys"] == []:
            state["keys"] = list(cd.PHRASE)
        if n >= 20 and n % 3 == 0 and state["keys"]:
            ch = state["keys"].pop(0)
            kb = state["kb"]
            kb.symbols = ch in ":/" or ch.isdigit() and False
            for face, (lab, kind) in kb._pages[kb.symbols]:
                if lab == ch:
                    p = at(*face.center); break
            pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=p, button=1))
            pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONUP, pos=p, button=1))
        if n > 400:
            pygame.event.post(pygame.event.Event(pygame.QUIT))
        return real_get()
    pygame.event.get = get
    return state

# capture the keyboard object created inside main()
orig_kb = cd.OnScreenKeyboard
state = scripted()
def make_kb(*a):
    k = orig_kb(*a); state["kb"] = k; return k
cd.OnScreenKeyboard = make_kb
ok = cd.main(max_seconds=60)
print("RESULT good run ->", ok)
assert ok, "a correct setup should report no problems"
