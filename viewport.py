"""
The game always draws on a fixed 800x600 canvas. This module puts that canvas into whatever
window the system gives us (any size, any shape) and turns pointer positions back into canvas
coordinates. We do the scaling ourselves instead of using SDL's SCALED flag, so it behaves the
same on Windows and on Android's Termux:X11.

Coordinates, in the order a tap passes through them:
    window  - what pygame reports (pixels of the real window)
    canvas  - the 800x600 picture the keyboard is drawn on
    scene   - the canvas, but moved by `lift` pixels. When the on-screen keyboard is up the scene
              is slid upward so the focused text box stays visible; scenes only ever see this one.

Every read of the pointer goes through this file: `convert_event()` for clicks and taps, and
`pointer_pos()` for "where is the pointer right now" (hover effects).
"""

import os
import time
import zlib

import pygame

import device

CANVAS_SIZE = (800, 600)        # the base size (and what desktop uses)
BASE_HEIGHT = 600               # the canvas is always this tall...
MIN_WIDTH, MAX_WIDTH = 800, 1400   # ...and, on Android, as wide as the screen's shape needs
PORTRAIT_WIDTH = 540            # a phone held upright: the canvas is this wide...
PORTRAIT_MIN_H, PORTRAIT_MAX_H = 720, 1300   # ...and as tall as the screen's shape needs
DESKTOP_SCALES = (1.0, 1.5, 2.0)   # the few window sizes on a PC (800x600, 1200x900, 1600x1200)


def choose_canvas(width, height):
    """The few canvas shapes the game is laid out for, picked from the REAL screen size.
    Upright phone: 540 wide, as tall as the screen's shape needs. Sideways phone: 600 tall, as
    wide as needed. Both fill the screen with no bars; the layout code positions things from
    the canvas size, so these are the only 'resize' cases there are."""
    if height > width * 1.1:
        tall = round(PORTRAIT_WIDTH * height / width)
        return (PORTRAIT_WIDTH, min(PORTRAIT_MAX_H, max(PORTRAIT_MIN_H, tall)))
    wide = round(BASE_HEIGHT * width / height)
    return (min(MAX_WIDTH, max(MIN_WIDTH, wide)), BASE_HEIGHT)


def desktop_window_sizes(desktop_w, desktop_h):
    """The window sizes that fit on this PC's desktop (with room for the title bar and taskbar)."""
    fits = [s for s in DESKTOP_SCALES
            if CANVAS_SIZE[0] * s <= desktop_w - 40 and CANVAS_SIZE[1] * s <= desktop_h - 120]
    return fits or [DESKTOP_SCALES[0]]
OFFSCREEN = (-10000, -10000)    # "the pointer is nowhere": nothing is hovered
STABLE_READS_NEEDED = 3        # the screen size must read the same this many times in a row...
STABLE_STEP_MS = 100            # ...this far apart (a phone is still rotating at launch)
STABLE_GIVE_UP_MS = 2500        # and if it never settles, go on with what we have
MIN_SURFACE = 100               # a window smaller than this is SDL mid-change, not a real size
SLOW_SCALE_SECONDS = 0.018      # smooth scaling a whole picture slower than this -> the fast kind
BAND = 24                       # the canvas is checked for changes in bands of this many rows
CLEANUP_FRAMES = 15             # after motion stops, repaint once in full (about half a second)
FULL_ABOVE = 0.6                # more than this share of rows changed: just send everything

if device.ANDROID:
    # Termux:X11 has no window manager: put the window in the corner. Must be set before the
    # display is created, which is why it happens when this file is imported.
    os.environ.setdefault("SDL_VIDEO_WINDOW_POS", "0,0")

# Events that mean "the window may be different now": look at it again before drawing anything.
_REFRESH_EVENTS = [getattr(pygame, name) for name in
                   ("VIDEORESIZE", "VIDEOEXPOSE", "WINDOWRESIZED", "WINDOWSIZECHANGED",
                    "WINDOWEXPOSED", "WINDOWRESTORED", "WINDOWSHOWN", "WINDOWMAXIMIZED",
                    "WINDOWFOCUSGAINED", "APP_DIDENTERFOREGROUND", "WINDOWENTER")
                   if hasattr(pygame, name)]
_MOUSE_EVENTS = (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION)


class Viewport:
    def __init__(self):
        self.canvas = None            # our own surface everything draws on
        self.size = CANVAS_SIZE       # its size: 800x600 on a PC; shaped like the screen on a phone
        self.margin = 0               # pixels kept free at each side of the screen (camera notch)
        self.origin = (0, 0)          # where the current screen's own area starts on the canvas
        self.android = False
        self.desktop = None           # (width, height) of the PC desktop
        self.window_scale = 1.0       # PC window size preset in use
        self.dest = pygame.Rect(0, 0, *CANVAS_SIZE)   # where the picture sits in the window
        self.scale = 1.0
        self.lift = 0                 # pixels the scene is slid up (on-screen keyboard)
        self.touch = False            # touch mode: there is no hover
        mode = os.environ.get("UNO_SCALE", "auto").lower()
        self._smooth_pref = mode != "fast"      # may smooth scaling be used at all?
        self.auto_scale = mode == "auto"        # switch to fast scaling if smooth is too slow
        self.smooth = self._smooth_pref
        self.scale_note = ""
        self.scale_ms = 0.0           # recent time spent scaling, in milliseconds (a diagnostic)
        self.ready = False            # a usable window exists and the layout matches it
        self.errors = 0               # display errors survived (see recover())
        self.events = []              # the last things the display did, newest last
        self.log_path = None
        self._seen = None             # the window surface the layout was made for
        self._win_size = None
        self._scaled = None           # the picture, scaled; our own surface, same format as canvas
        self._full = True             # next present() must repaint the whole window
        self._crcs = None             # checksum of each band of the canvas as last drawn
        self._track = True            # change tracking works (switched off if the canvas can't be read)
        self._idle = 0                # frames in a row with nothing changed
        self._cleanup = False         # partial updates were sent: repaint in full once it goes quiet
        self.stats = {"frames": 0, "skipped": 0, "partial": 0, "full": 0, "rows_sent": 0}

    # ---------------------------------------------------------------- log

    def log(self, text):
        """Keep a short record of what the display did. On a phone there is no console, so this is
        shown by the menu's "Screen info" button, saved to display.log, and added to crash reports."""
        stamp = time.strftime("%H:%M:%S")
        self.events.append(f"{stamp} {text}")
        del self.events[:-60]
        try:
            if self.log_path is None:
                import settings
                self.log_path = os.path.join(os.path.dirname(settings.SETTINGS_FILE), "display.log")
            with open(self.log_path, "w", encoding="utf-8") as f:
                f.write("\n".join(self.events) + "\n")
        except Exception:
            pass

    # ---------------------------------------------------------------- the window

    def live(self):
        """The window surface RIGHT NOW. SDL may replace it at any moment (rotation, switching
        apps), so it is fetched every time it is used and never kept."""
        return pygame.display.get_surface()

    @staticmethod
    def _usable(size):
        return size[0] >= MIN_SURFACE and size[1] >= MIN_SURFACE

    def open(self, android=None):
        """Create the window and canvas. -> the canvas to draw on."""
        self.android = device.ANDROID if android is None else android
        self.ready = False
        self._seen = None
        self.canvas = None
        info = pygame.display.Info()
        if self.android:
            if device.IN_TERMUX:
                # Termux has no window manager: a borderless window the size of the X display.
                w, h = info.current_w, info.current_h
                if not (320 <= w <= 8192 and 240 <= h <= 8192):
                    w, h = 1280, 720
                pygame.display.set_mode((w, h), pygame.NOFRAME)
            else:
                pygame.display.set_mode((0, 0), pygame.FULLSCREEN)   # a real Android app
            self._wait_until_stable()
            self._check_orientation()
            w, h = self.live().get_size()
            # UNO_MARGIN=4 keeps 4% free at each side (if a camera notch hides the corners).
            try:
                percent = min(15.0, max(0.0, float(os.environ.get("UNO_MARGIN", "0") or 0)))
            except ValueError:
                percent = 0.0
            self.margin = int(w * percent / 100)
        else:
            self.desktop = (info.current_w, info.current_h)
            self.window_scale = desktop_window_sizes(*self.desktop)[-1]
            if os.environ.get("UNO_WINDOW"):          # e.g. UNO_WINDOW=1.5
                try:
                    self.window_scale = float(os.environ["UNO_WINDOW"])
                except ValueError:
                    pass
            pygame.display.set_mode(self._window_pixels())   # a fixed size: no dragging
        live = self.live()
        if live is None or not self._usable(live.get_size()):
            self.log(f"no usable window ({live.get_size() if live else None}): using 1280x720")
            pygame.display.set_mode((1280, 720))
        self.poll()                                          # sets up the layout and the canvas
        return self.canvas

    def _wait_until_stable(self):
        """On a phone the window can still be changing when the game starts (the screen is
        rotating, SDL is making the surface). Take the size once it reads the same several times
        in a row, instead of building the whole UI around a number that is about to change."""
        waited, last, same = 0, None, 0
        while waited < STABLE_GIVE_UP_MS:
            pygame.event.pump()                  # let SDL deliver what it has been holding
            live = self.live()
            size = live.get_size() if live is not None else None
            if size is not None and self._usable(size):
                same = same + 1 if size == last else 0
                last = size
                if same >= STABLE_READS_NEEDED:
                    break
            pygame.time.wait(STABLE_STEP_MS)
            waited += max(1, STABLE_STEP_MS)
        self.log(f"window settled at {last} after {waited} ms" if same >= STABLE_READS_NEEDED
                 else f"window never settled (last {last}); going on with it")

    def _check_orientation(self):
        """The window and the display must agree whether the screen is upright or sideways. If they
        don't (a half-finished rotation), ask SDL for a fresh window once."""
        getter = getattr(pygame.display, "get_desktop_sizes", None)
        try:
            desk = getter()[0] if getter else None
        except Exception:
            desk = None
        live = self.live()
        if desk is None or live is None:
            return
        win = live.get_size()
        self.log(f"window {win}, display {desk}")
        if (win[0] > win[1]) != (desk[0] > desk[1]) and not device.IN_TERMUX:
            self.log("window and display disagree about the orientation: recreating the window")
            pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
            self._wait_until_stable()

    def _phone_canvas(self, w, h):
        if os.environ.get("UNO_FILL", "1") == "0":
            return CANVAS_SIZE
        return choose_canvas(w - 2 * self.margin, h)

    def _window_pixels(self):
        return (int(CANVAS_SIZE[0] * self.window_scale), int(CANVAS_SIZE[1] * self.window_scale))

    def cycle_window(self):
        """PC: switch to the next window size that fits the desktop (F4)."""
        if self.android or not self.desktop:
            return
        sizes = desktop_window_sizes(*self.desktop)
        later = [s for s in sizes if s > self.window_scale]
        self.window_scale = later[0] if later else sizes[0]
        pygame.display.set_mode(self._window_pixels())
        self._seen = None                        # poll() lays everything out again

    def poll(self):
        """Call at the START of every frame, before anything is drawn. Notices that the window
        changed (rotation, a new surface, a resize) and lays out again, so drawing never uses a
        layout made for a different window. -> True when the canvas was replaced (the screens must
        then be built again for its new size)."""
        live = self.live()
        if live is None:
            return False
        size = live.get_size()
        if not self._usable(size):               # SDL is in the middle of a change: wait
            if self.ready:
                self.log(f"window reports {size}: waiting")
            self.ready = False
            return False
        if self.ready and live is self._seen and size == self._win_size:
            return False
        old = self.size
        if self.android:
            self.size = self._phone_canvas(*size)
        replaced = self.canvas is None or self.size != old
        if replaced:
            self.canvas = pygame.Surface(self.size, 0, 32)   # 32-bit: every scaler accepts it
            self._crcs = None
        self._layout(live, size)
        self.log(f"window {size} -> canvas {self.size}, scale {self.scale:.2f}, "
                 f"picture {self.dest.w}x{self.dest.h}" + (" (new canvas)" if replaced else ""))
        return replaced

    def _layout(self, live, size):
        ww, wh = size
        cw, ch = self.size
        usable = ww - 2 * self.margin
        self.scale = min(usable / cw, wh / ch)
        dest = (max(1, int(cw * self.scale)), max(1, int(ch * self.scale)))
        self.dest = pygame.Rect(self.margin + (usable - dest[0]) // 2, (wh - dest[1]) // 2, *dest)
        # a whole-number scale is pixel-exact AND the cheapest kind
        whole = abs(self.scale - round(self.scale)) < 0.01
        self.smooth = self._smooth_pref and not whole
        self._scaled = (None if dest == self.size else pygame.Surface(dest, 0, 32))
        self._win_size = size
        self._seen = live
        self._full = True
        self._cleanup = False
        self.ready = True

    def recover(self, why):
        """A display call failed (SDL swapped the surface under us, say). Don't crash: forget what
        we know about the window and look at it again at the start of the next frame."""
        self.errors += 1
        self.log(f"display error: {why}")
        self._seen = None
        self._crcs = None
        self._full = True

    def note_event(self, event):
        """Call with every event: some mean the window may be different now."""
        if event.type in _REFRESH_EVENTS:
            self._seen = None                    # poll() will look at the window again
            self._full = True

    # ---------------------------------------------------------------- drawing out

    def apply_lift(self):
        """Slide what is on the canvas up by `lift` pixels (the keyboard covers the bottom)."""
        if self.lift > 0:
            self.canvas.scroll(0, -int(self.lift))

    def present(self):
        """Put the canvas on screen, sending as little as possible:
        nothing if the picture is unchanged, only the changed strips if some changed (each
        scaled and sent on its own), everything after a resize. Once motion stops, the whole
        picture is repainted once so partial updates can never leave a faint seam behind."""
        window = self.live()
        if (window is None or not self.ready or window is not self._seen
                or window.get_size() != self._win_size):
            return                               # the window changed: poll() deals with it next frame
        try:
            self._present(window)
        except (pygame.error, ValueError) as problem:
            self.recover(repr(problem))

    def _present(self, window):
        height = self.size[1]
        self.stats["frames"] += 1
        runs = self._changed_rows()             # [(first row, last row + 1), ...]; [] = unchanged

        if self._full:
            window.fill((0, 0, 0))               # black side bars: painted once, never re-sent
            self._paint(window, 0, height)
            pygame.display.flip()                # first frame / after a resize: the whole window
            self._full = False
            self._cleanup = False
            self._count("full", height)
        elif not runs:
            self.stats["skipped"] += 1
            self._idle += 1
            if self._cleanup and self._idle >= CLEANUP_FRAMES:
                self._send_all(window)
        else:
            self._idle = 0
            rows = sum(y1 - y0 for y0, y1 in runs)
            if rows > FULL_ABOVE * height:
                self._send_all(window)
            else:
                rects = [self._paint(window, y0, y1) for y0, y1 in runs]
                pygame.display.update(rects)
                self._cleanup = True
                self._count("partial", rows)

    def _send_all(self, window):
        self._paint(window, 0, self.size[1])
        pygame.display.update(self.dest)
        self._cleanup = False
        self._count("full", self.size[1])

    def _count(self, kind, rows):
        self.stats[kind] += 1
        self.stats["rows_sent"] += rows

    def _changed_rows(self):
        """Compare the canvas with the last one: -> the strips (y0, y1) that changed."""
        height = self.size[1]
        if not self._track:
            return [(0, height)]
        try:
            raw = self.canvas.get_buffer().raw
            pitch = self.canvas.get_pitch()
            data = memoryview(raw)
            crcs = [zlib.crc32(data[y * pitch:min(y + BAND, height) * pitch])
                    for y in range(0, height, BAND)]
        except Exception:                        # can't read the pixels: send everything, always
            self._track = False
            return [(0, height)]
        old, self._crcs = self._crcs, crcs
        if old is None or len(old) != len(crcs):
            return [(0, height)]
        runs = []
        for i, (a, b) in enumerate(zip(old, crcs)):
            if a == b:
                continue
            if runs and i - runs[-1][1] <= 1:    # next to the last strip (or one band apart): merge
                runs[-1][1] = i + 1
            else:
                runs.append([i, i + 1])
        return [(i0 * BAND, min(height, i1 * BAND)) for i0, i1 in runs]

    def _paint(self, window, y0, y1):
        """Scale canvas rows y0..y1 and copy them to the window. -> the screen rectangle sent.
        Scaling only ever touches OUR surfaces (canvas and `_scaled`, both 32-bit); the window,
        whose pixel format we don't control, only receives a plain copy."""
        height, dh = self.size[1], self.dest.h
        full = (y0, y1) == (0, height)
        a, b = y0 * dh // height, y1 * dh // height          # the rows to show, in picture pixels
        if self._scaled is None:                             # 1:1, nothing to scale
            area = pygame.Rect(0, y0, self.size[0], y1 - y0)
            window.blit(self.canvas, (self.dest.x, self.dest.y + y0), area)
            return pygame.Rect(self.dest) if full else pygame.Rect(
                self.dest.x, self.dest.y + y0, self.dest.w, y1 - y0)

        margin = 0 if full else 2                # a few extra rows so the strip's edges scale right
        m0, m1 = max(0, y0 - margin), min(height, y1 + margin)
        r0, r1 = m0 * dh // height, m1 * dh // height
        started = time.perf_counter()
        source = self.canvas if (m0, m1) == (0, height) else self.canvas.subsurface(
            pygame.Rect(0, m0, self.size[0], m1 - m0))
        size = (self.dest.w, r1 - r0)
        target = self._scaled if size[1] == dh else self._scaled.subsurface(
            pygame.Rect(0, r0, *size))
        scaler = pygame.transform.smoothscale if self.smooth else pygame.transform.scale
        try:
            scaler(source, size, target)
        except (ValueError, pygame.error):
            self.smooth = self._smooth_pref = False          # fall back to the plain scaler for good
            pygame.transform.scale(source, size, target)
        spent = (time.perf_counter() - started) * height / max(1, m1 - m0)   # cost per whole picture
        self.scale_ms = self.scale_ms * 0.9 + spent * 1000 * 0.1
        if self.smooth and self.auto_scale and self.scale_ms > SLOW_SCALE_SECONDS * 1000:
            self.smooth = self._smooth_pref = False
            self.scale_note = (f"smooth scaling took {self.scale_ms:.0f} ms a frame, "
                               "switched to fast scaling")
            self.log(self.scale_note)

        shown = pygame.Rect(0, a, self.dest.w, b - a)
        window.blit(self._scaled, (self.dest.x, self.dest.y + a), shown)
        return pygame.Rect(self.dest) if full else pygame.Rect(
            self.dest.x, self.dest.y + a, self.dest.w, b - a)

    # ---------------------------------------------------------------- pointer in

    def window_to_canvas(self, pos):
        """A position in the real window -> a position on the canvas.
        Positions over the black bars come out negative or beyond the canvas (never clamped, so a
        tap on a bar counts as 'a tap on nothing', not as a tap on the nearest edge)."""
        return (int(round((pos[0] - self.dest.x) / self.scale)),
                int(round((pos[1] - self.dest.y) / self.scale)))

    def canvas_to_scene(self, pos):
        return (pos[0] - self.origin[0], pos[1] + int(self.lift) - self.origin[1])

    def convert_event(self, event):
        """A mouse/touch event with its position in CANVAS coordinates (others pass through)."""
        if event.type in _MOUSE_EVENTS and hasattr(event, "pos"):
            data = dict(event.dict)
            data["pos"] = self.window_to_canvas(event.pos)
            return pygame.event.Event(event.type, data)
        return event

    def scene_event(self, event):
        """The same event, moved into SCENE coordinates (for the screens)."""
        if event.type in _MOUSE_EVENTS and hasattr(event, "pos"):
            data = dict(event.dict)
            data["pos"] = self.canvas_to_scene(event.pos)
            return pygame.event.Event(event.type, data)
        return event

    def pointer_pos(self):
        """Where the pointer is, in scene coordinates, for hover effects. In touch mode there
        is no hover (the pointer would just sit on the last tap), so it is 'nowhere'."""
        if self.touch:
            return OFFSCREEN
        return self.canvas_to_scene(self.window_to_canvas(pygame.mouse.get_pos()))

    def describe(self):
        """Plain-text facts about the screen, for the menu's "Screen info" button."""
        win = self.live()
        size = win.get_size() if win else (0, 0)
        shape = "upright" if size[1] > size[0] else "sideways"
        return ([f"screen {size[0]}x{size[1]} ({shape})  driver {pygame.display.get_driver()}",
                 f"canvas {self.size[0]}x{self.size[1]}  scale {self.scale:.2f}  "
                 f"{'smooth' if self.smooth else 'fast'}  errors {self.errors}",
                 f"picture {self.dest.w}x{self.dest.h} at ({self.dest.x},{self.dest.y})",
                 f"android {device.ANDROID}  termux {device.IN_TERMUX}",
                 f"sent: {self.stats['skipped']} idle, {self.stats['partial']} partial, "
                 f"{self.stats['full']} full frames"] + self.events[-6:])


view = Viewport()


def pointer_pos():
    return view.pointer_pos()
