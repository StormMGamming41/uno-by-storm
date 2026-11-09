"""
The on-screen keyboard (touch mode).

Android's own keyboard doesn't reliably send key presses to Termux:X11, so the game draws its
own. It slides up from the bottom of the canvas while a text box is focused, and the screen is
lifted by the same amount (see viewport.py) so the box you are typing in stays visible.

Keys: number row, letters with Shift (tap = one capital, double-tap = caps lock), a symbols page
(it has `:` and `/`, which addresses need), Paste, Hide, Go and Backspace (hold to repeat).
Keys the focused box would reject (e.g. letters in the port box) are greyed out.

Everything here works in CANVAS coordinates, because the keyboard is drawn after the screen has
been lifted.
"""

import pygame

import clipboard
from anim import approach
from theme import theme
from ui_objects import fit_text, luminance, text_surface
MAX_KEYS_WIDTH = 1200           # on a very wide screen the keys stop growing and stay centred
GAP, PAD_X, PAD_Y = 5, 6, 7
ROWS = 5
KEY_H_UPRIGHT, KEY_H_SIDEWAYS = 60, 48      # taller keys when the phone is upright (more room)
MARGIN = 14                     # space kept between the focused box and the keyboard
REPEAT_DELAY, REPEAT_EVERY = 0.40, 0.06
DOUBLE_TAP = 0.5                # seconds between two Shift taps that mean "caps lock"

BOTTOM = [("?123", "sym", 1.5), ("Paste", "paste", 1.5), ("-", "char", 1.0),
          ("space", "space", 2.5), (".", "char", 1.0), ("Hide", "hide", 1.25),
          ("Go", "go", 1.25)]


def _chars(text, units=1.0):
    return [(c, "char", units) for c in text]


LETTERS = [
    _chars("1234567890"),
    _chars("qwertyuiop"),
    [("", "pad", 0.5)] + _chars("asdfghjkl") + [("", "pad", 0.5)],
    [("Shift", "shift", 1.5)] + _chars("zxcvbnm") + [("Del", "back", 1.5)],
    BOTTOM,
]
SYMBOLS = [
    _chars("1234567890"),
    _chars(":/.-_@#&+="),
    [("", "pad", 0.5)] + _chars("()$%!?,;'") + [("", "pad", 0.5)],
    _chars("\"<>[]{}~") + [("Del", "back", 2.0)],
    [("abc", "sym", 1.5)] + BOTTOM[1:],
]


def _build(rows, width, top, key_h):
    """-> [(face rect, key)] for a keyboard sitting with its top edge at `top`."""
    keys_w = min(width, MAX_KEYS_WIDTH)
    left = (width - keys_w) // 2
    unit = (keys_w - 2 * PAD_X + GAP) / 10
    out = []
    for r, row in enumerate(rows):
        x = left + PAD_X
        y = top + PAD_Y + r * (key_h + GAP)
        for label, kind, units in row:
            width = units * unit
            if kind != "pad":
                face = pygame.Rect(round(x), y, round(width - GAP), key_h)
                out.append((face, (label, kind)))
            x += width
    return out


class OnScreenKeyboard:
    def __init__(self, width=800, height=600):
        self.width = width            # the canvas size varies between screens
        key_h = KEY_H_UPRIGHT if height > width else KEY_H_SIDEWAYS
        self.key_h = key_h
        self.height = ROWS * key_h + (ROWS - 1) * GAP + 2 * PAD_Y   # the keyboard's own height
        self.top = height - self.height                            # where it sits when fully up
        self.t = 0.0                  # 0 = hidden below the screen, 1 = fully up
        self.symbols = False
        self.shift = 0                # 0 off, 1 next letter, 2 caps lock
        self._last_shift_tap = -10.0
        self._clock = 0.0
        self.pressed = None           # the key currently held down
        self.held_for = 0.0
        self._repeating = 0.0
        self.note = ""                # a short message above the keyboard ("Pasting...")
        self.note_time = 0.0
        self._paste_wait = 0
        self._pages = {False: _build(LETTERS, width, self.top, key_h),
                       True: _build(SYMBOLS, width, self.top, key_h)}

    # ---------------------------------------------------------------- geometry

    @property
    def slide(self):
        """How many pixels it is still below its resting place (0 when fully up)."""
        return int(round(self.height * (1.0 - self.t)))

    @property
    def usable(self):
        return self.t > 0.8           # while it's still sliding in, taps pass through

    def covers(self, pos):
        """Is a canvas position on the keyboard? (Then the screen behind must not get the tap.)"""
        return self.t > 0.05 and pos[1] >= self.top + self.slide

    def lift_for(self, box, origin_y=0):
        """How far the picture must slide up so `box` ends above the keyboard.
        `origin_y`: where the box's screen starts on the canvas (it is centred on tall screens)."""
        if box is None:
            return 0.0
        return max(0.0, origin_y + box.rect.bottom + MARGIN - self.top) * self.t

    def _key_at(self, pos):
        y = pos[1] - self.slide
        for face, key in self._pages[self.symbols]:
            if face.inflate(GAP, GAP).collidepoint(pos[0], y):     # gaps belong to a key too
                return key
        return None

    # ---------------------------------------------------------------- input

    def handle_event(self, event, box):
        """-> None if the event isn't for the keyboard, "hide" / "go" for those keys, else "used"."""
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if not self.covers(event.pos):
                return None
            if not self.usable:
                return "used"
            key = self._key_at(event.pos)
            self.pressed = key
            self.held_for = self._repeating = 0.0
            return self._press(key, box) if key else "used"
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1 and self.pressed is not None:
            self.pressed = None
            return "used"        # the end of a tap that began on the keyboard
        return None

    def _press(self, key, box):
        label, kind = key
        if kind == "char":
            ch = label.upper() if (self.shift and label.isalpha()) else label
            if box is not None and box.accepts(ch):
                box.insert(ch)
                if self.shift == 1:
                    self.shift = 0
        elif kind == "space":
            if box is not None and box.accepts(" "):
                box.insert(" ")
        elif kind == "back":
            if box is not None:
                box.backspace()
        elif kind == "shift":
            if self.shift == 0:
                self.shift = 1
            elif self.shift == 1 and self._clock - self._last_shift_tap < DOUBLE_TAP:
                self.shift = 2
            else:
                self.shift = 0
            self._last_shift_tap = self._clock
        elif kind == "sym":
            self.symbols = not self.symbols
        elif kind == "paste":
            self._say("Pasting...", 30.0)   # shown for a frame or two; replaced when done
            self._paste_wait = 2
        elif kind == "hide":
            return "hide"
        elif kind == "go":
            return "go"
        return "used"

    def _say(self, text, seconds=2.0):
        self.note, self.note_time = text, seconds

    # ---------------------------------------------------------------- per frame

    def update(self, dt, box, shown):
        """`shown`: should the keyboard be up? `box`: the focused TextBox (or None)."""
        self._clock += dt
        self.t = approach(self.t, 1.0 if shown else 0.0, dt, 14)
        self.note_time = max(0.0, self.note_time - dt)
        if self.note_time == 0.0:
            self.note = ""
        if not shown:
            self.pressed = None
            self._paste_wait = 0

        if self._paste_wait:     # the clipboard can take a moment: show "Pasting..." first
            self._paste_wait -= 1
            if self._paste_wait == 0:
                self._do_paste(box)

        if self.pressed and self.pressed[1] == "back":      # hold Backspace to keep deleting
            self.held_for += dt
            if self.held_for >= REPEAT_DELAY:
                self._repeating += dt
                while self._repeating >= REPEAT_EVERY:
                    self._repeating -= REPEAT_EVERY
                    if box is not None:
                        box.backspace()

    def _do_paste(self, box):
        text = clipboard.paste()
        if box is None:
            self.note = ""
        elif text:
            box.insert(text)
            self._say("Pasted")
        elif clipboard.unavailable_reason:
            self._say("Clipboard off: " + clipboard.unavailable_reason, 4.0)
        else:
            self._say("Clipboard is empty")

    # ---------------------------------------------------------------- drawing

    def draw(self, screen, box):
        if self.t < 0.02:
            return
        slide = self.slide
        panel = pygame.Rect(0, self.top + slide, self.width, self.height)
        pygame.draw.rect(screen, theme["panel_alt"], panel)
        pygame.draw.line(screen, theme["border"], panel.topleft, panel.topright, 2)

        for face, key in self._pages[self.symbols]:
            label, kind = key
            face = face.move(0, slide)
            is_char = kind in ("char",)
            ch = label.upper() if (self.shift and label.isalpha()) else label
            usable = box is None or not is_char or box.accepts(ch)
            down = key == self.pressed

            if not usable:
                fill, ink = theme["disabled"], theme["disabled_text"]
            elif kind == "go":
                fill, ink = theme["btn_green"], (255, 255, 255)
            elif kind == "shift" and self.shift:
                fill, ink = theme["accent"], (255, 255, 255)
            elif kind in ("char", "space"):
                fill, ink = theme["panel"], theme["text"]
            else:
                fill, ink = theme["btn_neutral"], theme["text"]
            if down and usable:
                fill = tuple(max(0, int(c * 0.78)) if luminance(fill) > 0.5
                             else min(255, int(c * 1.25) + 12) for c in fill)

            pygame.draw.rect(screen, theme["shadow"], face.move(0, 2), border_radius=8)
            pygame.draw.rect(screen, fill, face.move(0, 1 if down else 0), border_radius=8)

            if kind == "shift":
                shown = "CAPS" if self.shift == 2 else "Shift"
            elif kind == "space":
                shown = ""
            else:
                shown = ch
            if shown:
                size = 26 if is_char else 18
                surf = text_surface(fit_text(shown, size, face.width - 6), size, ink)
                screen.blit(surf, surf.get_rect(center=face.move(0, 1 if down else 0).center))

        if self.note:
            surf = text_surface(fit_text(self.note, 18, self.width - 60), 18, theme["text"])
            pill = surf.get_rect(center=(self.width // 2, self.top + slide - 18)).inflate(24, 10)
            pygame.draw.rect(screen, theme["panel"], pill, border_radius=12)
            pygame.draw.rect(screen, theme["border"], pill, width=1, border_radius=12)
            screen.blit(surf, surf.get_rect(center=pill.center))
