"""
A STAND-IN for pygame, built on PIL, used only to test the game where real pygame can't be
installed. It implements just the parts of pygame this game uses, with the same names and
the same behaviour for those parts, and draws real pictures so screenshots can be inspected.

It is NOT pygame: it can't tell us about SDL, X11, Termux:X11, touch drivers, real speed or
how real fonts look. Tests passing here means the game's own logic and layout work; it says
nothing certain about a real phone.

One thing it does model carefully, because the game depends on it: the window has two images,
what the program has drawn (`display._window`) and what is actually on screen
(`display._screen`). `flip()` copies everything; `update(rect)` copies only that rectangle. So
a game that forgets to send an area shows a stale area in the screenshot, as in real life.
"""

import os
import types

from PIL import Image, ImageDraw, ImageFont

# ------------------------------------------------------------------ constants
QUIT, KEYDOWN, KEYUP, TEXTINPUT = 256, 768, 769, 771
MOUSEMOTION, MOUSEBUTTONDOWN, MOUSEBUTTONUP, MOUSEWHEEL = 1024, 1025, 1026, 1027
FINGERDOWN, FINGERUP, FINGERMOTION = 1792, 1793, 1794
VIDEORESIZE, VIDEOEXPOSE = 32769, 32770
WINDOWSHOWN, WINDOWEXPOSED, WINDOWRESIZED, WINDOWSIZECHANGED = 32774, 32775, 32777, 32778
WINDOWMAXIMIZED, WINDOWRESTORED = 32779, 32781
SRCALPHA, NOFRAME, RESIZABLE, FULLSCREEN = 0x10000, 0x20, 0x10, 0x80000000
K_BACKSPACE, K_RETURN, K_ESCAPE, K_KP_ENTER = 8, 13, 27, 1073741912
K_v, K_a, K_z = 118, 97, 122
K_F1, K_F2, K_F3, K_F4 = 1073741882, 1073741883, 1073741884, 1073741885
KMOD_CTRL, KMOD_META = 0x00C0, 0x0C00
SCRAP_TEXT = "text/plain"
version = types.SimpleNamespace(ver="fake-pil")


class error(Exception):
    pass


def get_sdl_version():
    return (0, 0, 0)


def init():
    return (0, 0)


def quit():
    pass


# ------------------------------------------------------------------ Rect
class Rect:
    def __init__(self, *a):
        if len(a) == 1:
            a = tuple(a[0]) if not isinstance(a[0], Rect) else a[0].as_tuple()
        if len(a) == 2:
            (x, y), (w, h) = a
        else:
            x, y, w, h = a
        self.x, self.y, self.w, self.h = int(x), int(y), int(w), int(h)

    def as_tuple(self):
        return (self.x, self.y, self.w, self.h)

    def __iter__(self):
        return iter(self.as_tuple())

    def __getitem__(self, i):
        return self.as_tuple()[i]

    def __len__(self):
        return 4

    def __eq__(self, other):
        try:
            return self.as_tuple() == tuple(Rect(other).as_tuple())
        except Exception:
            return False

    def __repr__(self):
        return f"<rect({self.x}, {self.y}, {self.w}, {self.h})>"

    def copy(self):
        return Rect(self.as_tuple())

    # edges
    left = property(lambda s: s.x, lambda s, v: setattr(s, "x", int(v)))
    top = property(lambda s: s.y, lambda s, v: setattr(s, "y", int(v)))
    width = property(lambda s: s.w, lambda s, v: setattr(s, "w", int(v)))
    height = property(lambda s: s.h, lambda s, v: setattr(s, "h", int(v)))
    right = property(lambda s: s.x + s.w, lambda s, v: setattr(s, "x", int(v) - s.w))
    bottom = property(lambda s: s.y + s.h, lambda s, v: setattr(s, "y", int(v) - s.h))
    centerx = property(lambda s: s.x + s.w // 2, lambda s, v: setattr(s, "x", int(v) - s.w // 2))
    centery = property(lambda s: s.y + s.h // 2, lambda s, v: setattr(s, "y", int(v) - s.h // 2))

    @property
    def size(self):
        return (self.w, self.h)

    @size.setter
    def size(self, v):
        self.w, self.h = int(v[0]), int(v[1])

    def _pt(name, fx, fy):   # a corner/edge-midpoint property, built from two edge functions
        def get(s):
            return (fx(s), fy(s))

        def put(s, v):
            if fx(s) != v[0]:
                s.x += int(v[0]) - fx(s)
            if fy(s) != v[1]:
                s.y += int(v[1]) - fy(s)
        return property(get, put)

    topleft = _pt("topleft", lambda s: s.x, lambda s: s.y)
    topright = _pt("topright", lambda s: s.x + s.w, lambda s: s.y)
    bottomleft = _pt("bottomleft", lambda s: s.x, lambda s: s.y + s.h)
    bottomright = _pt("bottomright", lambda s: s.x + s.w, lambda s: s.y + s.h)
    center = _pt("center", lambda s: s.x + s.w // 2, lambda s: s.y + s.h // 2)
    midleft = _pt("midleft", lambda s: s.x, lambda s: s.y + s.h // 2)
    midright = _pt("midright", lambda s: s.x + s.w, lambda s: s.y + s.h // 2)
    midtop = _pt("midtop", lambda s: s.x + s.w // 2, lambda s: s.y)
    midbottom = _pt("midbottom", lambda s: s.x + s.w // 2, lambda s: s.y + s.h)

    def collidepoint(self, *p):
        x, y = p[0] if len(p) == 1 else p
        return self.x <= x < self.x + self.w and self.y <= y < self.y + self.h

    def colliderect(self, o):
        o = Rect(o)
        return self.x < o.right and o.x < self.right and self.y < o.bottom and o.y < self.bottom

    def move(self, dx, dy):
        return Rect(self.x + dx, self.y + dy, self.w, self.h)

    def inflate(self, dx, dy):
        return Rect(self.x - dx // 2, self.y - dy // 2, self.w + dx, self.h + dy)

    def union(self, o):
        o = Rect(o)
        x, y = min(self.x, o.x), min(self.y, o.y)
        return Rect(x, y, max(self.right, o.right) - x, max(self.bottom, o.bottom) - y)

    def clip(self, o):
        o = Rect(o)
        x, y = max(self.x, o.x), max(self.y, o.y)
        r, b = min(self.right, o.right), min(self.bottom, o.bottom)
        return Rect(x, y, max(0, r - x), max(0, b - y))


# ------------------------------------------------------------------ Surface
def _rgba(color):
    c = tuple(int(v) for v in color)
    return c + (255,) if len(c) == 3 else c[:4]


class Surface:
    def __init__(self, size, flags=0, depth=0, masks=None, _img=None):
        self.has_alpha = bool(flags & SRCALPHA)
        self._img = _img if _img is not None else Image.new(
            "RGBA", (max(1, int(size[0])), max(1, int(size[1]))),
            (0, 0, 0, 0) if self.has_alpha else (0, 0, 0, 255))
        self._alpha = 255
        self._root, self._off = None, (0, 0)
        self._dead = False          # True once SDL has replaced this window surface

    def _check_alive(self):
        if self._dead:
            raise error("display Surface quit")

    def _resolve(self):
        """(the image really being drawn on, offset of this surface inside it)"""
        self._check_alive()
        if self._root is None:
            return self._img, (0, 0)
        img, off = self._root._resolve()
        return img, (off[0] + self._off[0], off[1] + self._off[1])

    def get_size(self):
        return (self.w, self.h)

    @property
    def w(self):
        return self._img.width

    @property
    def h(self):
        return self._img.height

    def get_width(self):
        return self.w

    def get_height(self):
        return self.h

    def get_rect(self, **kw):
        r = Rect(0, 0, self.w, self.h)
        for k, v in kw.items():
            setattr(r, k, v)
        return r

    def copy(self):
        s = Surface((1, 1), _img=self._img.copy())
        s.has_alpha, s._alpha = self.has_alpha, self._alpha
        return s

    def convert_alpha(self):
        s = self.copy()
        s.has_alpha = True
        return s

    def convert(self):
        s = self.copy()
        s.has_alpha = False
        return s

    def set_alpha(self, a):
        self._alpha = 255 if a is None else int(a)

    def subsurface(self, rect):
        self._check_alive()
        r = Rect(rect)
        if r.x < 0 or r.y < 0 or r.right > self.w or r.bottom > self.h:
            raise ValueError("subsurface rectangle outside surface area")
        s = Surface((r.w, r.h))
        s._root, s._off = self, (r.x, r.y)
        return s

    def get_at(self, pos):
        img, off = self._resolve()
        return img.getpixel((pos[0] + off[0], pos[1] + off[1]))

    def fill(self, color, rect=None):
        img, off = self._resolve()
        r = Rect(rect) if rect is not None else Rect(0, 0, self.w, self.h)
        img.paste(_rgba(color), (r.x + off[0], r.y + off[1], r.right + off[0], r.bottom + off[1]))

    def blit(self, src, dest, area=None):
        img, off = self._resolve()
        piece = src._resolve()[0]
        so = src._resolve()[1]
        if src._root is not None:   # a sub-surface: cut its own area out of the root image
            piece = piece.crop((so[0], so[1], so[0] + src.w, so[1] + src.h))
        if area is not None:
            a = Rect(area)
            piece = piece.crop((a.x, a.y, a.right, a.bottom))
        x, y = (dest.x, dest.y) if isinstance(dest, Rect) else (dest[0], dest[1])
        x, y = int(x) + off[0], int(y) + off[1]
        if src._alpha != 255:
            piece = piece.copy()
            piece.putalpha(piece.getchannel("A").point(lambda v: v * src._alpha // 255))
            img.paste(piece, (x, y), piece.getchannel("A"))
        elif src.has_alpha:
            img.paste(piece, (x, y), piece.getchannel("A"))
        else:
            img.paste(piece, (x, y))

    def scroll(self, dx=0, dy=0):
        img, off = self._resolve()
        box = (off[0], off[1], off[0] + self.w, off[1] + self.h)
        region = img.crop(box)
        src = (max(0, -dx), max(0, -dy), self.w - max(0, dx), self.h - max(0, dy))
        dst = (max(0, dx), max(0, dy))
        img.paste(region.crop(src), (box[0] + dst[0], box[1] + dst[1]))

    def get_pitch(self):
        return self.w * 4

    def get_buffer(self):
        img, off = self._resolve()
        if self._root is not None:
            img = img.crop((off[0], off[1], off[0] + self.w, off[1] + self.h))
        return types.SimpleNamespace(raw=img.tobytes())

    def _write_img(self, img):
        target, off = self._resolve()
        target.paste(img, off)


# ------------------------------------------------------------------ draw
def _prep(surface):
    img, off = surface._resolve()
    return ImageDraw.Draw(img), off


def _draw_rect(surface, color, rect, width=0, border_radius=0, **_):
    d, off = _prep(surface)
    r = Rect(rect)
    if r.w <= 0 or r.h <= 0:
        return
    box = [r.x + off[0], r.y + off[1], r.right - 1 + off[0], r.bottom - 1 + off[1]]
    fill, outline = (_rgba(color), None) if width == 0 else (None, _rgba(color))
    kw = dict(fill=fill, outline=outline, width=max(1, width))
    if border_radius > 0:
        d.rounded_rectangle(box, radius=min(border_radius, min(r.w, r.h) // 2), **kw)
    else:
        d.rectangle(box, **kw)


def _draw_circle(surface, color, center, radius, width=0, **_):
    d, off = _prep(surface)
    cx, cy = center[0] + off[0], center[1] + off[1]
    fill, outline = (_rgba(color), None) if width == 0 else (None, _rgba(color))
    d.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=fill,
              outline=outline, width=max(1, width))


def _draw_ellipse(surface, color, rect, width=0, **_):
    d, off = _prep(surface)
    r = Rect(rect)
    fill, outline = (_rgba(color), None) if width == 0 else (None, _rgba(color))
    d.ellipse([r.x + off[0], r.y + off[1], r.right - 1 + off[0], r.bottom - 1 + off[1]],
              fill=fill, outline=outline, width=max(1, width))


def _draw_line(surface, color, start, end, width=1):
    d, off = _prep(surface)
    d.line([(start[0] + off[0], start[1] + off[1]), (end[0] + off[0], end[1] + off[1])],
           fill=_rgba(color), width=max(1, int(width)))


def _draw_polygon(surface, color, points, width=0):
    d, off = _prep(surface)
    d.polygon([(p[0] + off[0], p[1] + off[1]) for p in points], fill=_rgba(color))


draw = types.SimpleNamespace(rect=_draw_rect, circle=_draw_circle, ellipse=_draw_ellipse,
                             line=_draw_line, polygon=_draw_polygon)

# ------------------------------------------------------------------ font
_FONT_FILES = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
               "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]


class Font:
    def __init__(self, path, size):
        self.size_px = size
        pil_size = max(6, round(size * 0.78))
        for f in _FONT_FILES:
            if os.path.exists(f):
                self._f = ImageFont.truetype(f, pil_size)
                break
        else:
            self._f = ImageFont.load_default(pil_size)

    def get_height(self):
        a, d = self._f.getmetrics()
        return a + d

    def size(self, text):
        return (int(self._f.getlength(text) + 0.999), self.get_height())

    def render(self, text, antialias, color, background=None):
        w, h = self.size(text)
        img = Image.new("RGBA", (max(1, w), h), (0, 0, 0, 0))
        ImageDraw.Draw(img).text((0, 0), text, font=self._f, fill=_rgba(color))
        s = Surface((1, 1), _img=img)
        s.has_alpha = True
        return s


font = types.SimpleNamespace(init=lambda: None, quit=lambda: None, Font=Font)


# ------------------------------------------------------------------ transform
class _Transform:
    calls = {"scale": 0, "smoothscale": 0}

    def _do(self, name, src, size, dest, resample):
        self.calls[name] += 1
        img = src._resolve()[0]
        if src._root is not None:
            o = src._resolve()[1]
            img = img.crop((o[0], o[1], o[0] + src.w, o[1] + src.h))
        img = img.resize((int(size[0]), int(size[1])), resample)
        if dest is not None:
            if dest.get_size() != tuple(size):
                raise ValueError("Destination surface not the same size.")
            dest._write_img(img)
            return dest
        s = Surface((1, 1), _img=img)
        s.has_alpha = src.has_alpha
        return s

    def scale(self, src, size, dest=None):
        return self._do("scale", src, size, dest, Image.NEAREST)

    def smoothscale(self, src, size, dest=None):
        return self._do("smoothscale", src, size, dest, Image.BILINEAR)


transform = _Transform()


# ------------------------------------------------------------------ events, mouse, key, time
class Event:
    def __init__(self, type, *args, **kw):
        object.__setattr__(self, "type", type)
        data = dict(args[0]) if args else {}
        data.update(kw)
        object.__setattr__(self, "dict", data)

    def __getattr__(self, name):
        try:
            return self.__dict__["dict"][name]
        except KeyError:
            raise AttributeError(name)

    def __repr__(self):
        return f"<Event({self.type} {self.dict})>"


class _EventModule:
    Event = Event

    def __init__(self):
        self.queue = []

    def get(self):
        out, self.queue = self.queue, []
        return out

    def post(self, e):
        self.queue.append(e)

    def pump(self):
        if hasattr(self, "on_pump"):
            self.on_pump()


event = _EventModule()


class _Mouse:
    pos = (0, 0)

    def get_pos(self):
        return self.pos


mouse = _Mouse()
key = types.SimpleNamespace(set_repeat=lambda *a: None, get_mods=lambda: 0)


class _Clock:
    last_fps = None

    def tick(self, fps=0):
        _Clock.last_fps = fps
        return int(1000 / fps) if fps else 0

    def get_fps(self):
        return float(_Clock.last_fps or 0)


_ticks = [0]


def _wait(ms):
    _ticks[0] += int(ms)
    return int(ms)


def _get_ticks():
    _ticks[0] += 1
    return _ticks[0]


time = types.SimpleNamespace(Clock=_Clock, wait=_wait, get_ticks=_get_ticks)


class _Scrap:
    data = None

    def init(self):
        pass

    def put(self, kind, data):
        self.data = data

    def get(self, kind):
        return self.data


scrap = _Scrap()


# ------------------------------------------------------------------ display
class _Display:
    def __init__(self):
        self._desktop = (1280, 720)      # what Info() reports before a window exists
        self._window = None              # what the program has drawn
        self._screen = None              # what is actually showing
        self.log = []                    # every flip()/update(rect) sent to the "screen"
        self.caption = ""
        self.flags = 0
        self._reported_desktop = None    # test hook: what get_desktop_sizes() claims

    def init(self):
        pass

    def quit(self):
        pass

    def get_driver(self):
        return "fake"

    def Info(self):
        return types.SimpleNamespace(current_w=self._desktop[0], current_h=self._desktop[1])

    def set_caption(self, text, *a):
        self.caption = text

    def set_mode(self, size=(0, 0), flags=0, *a, **k):
        if tuple(size) == (0, 0):
            size = self._desktop
        if not (flags & RESIZABLE) and not (flags & FULLSCREEN) and not (flags & NOFRAME):
            pass   # a normal fixed-size window
        self.flags = flags
        if self._window is not None:
            self._window._dead = True
        self._window = Surface(size)
        self._screen = Image.new("RGB", tuple(size), (0, 0, 0))
        self.log.append(("set_mode", tuple(size), flags))
        return self._window

    def get_surface(self):
        return self._window

    def get_window_size(self):
        return self._window.get_size()

    def get_desktop_sizes(self):
        return [self._reported_desktop or self._desktop]

    def flip(self):
        self._screen.paste(self._window._img.convert("RGB"))
        self.log.append("flip")

    def update(self, rect=None):
        if rect is None:
            return self.flip()
        if isinstance(rect, list):
            for one in rect:
                self.update(one)
            return
        r = Rect(rect)
        box = (r.x, r.y, r.right, r.bottom)
        self._screen.paste(self._window._img.crop(box).convert("RGB"), (r.x, r.y))
        self.log.append(("update", r.as_tuple()))

    # --- test helpers (not in real pygame)
    def _resize(self, size):
        """The window changes size (a drag on a PC, a rotation on a phone): SDL hands out a NEW
        surface and the old one dies."""
        if self._window is not None:
            self._window._dead = True
        self._window = Surface(size)
        self._screen = Image.new("RGB", tuple(size), (0, 0, 0))
        if min(size) >= 100:
            self._desktop = tuple(size)          # a rotation changes the display's size too
        event.post(Event(VIDEORESIZE, size=tuple(size), w=size[0], h=size[1]))


    def _replace_surface(self, post_event=False):
        """SDL recreates the window surface at the SAME size (app switch, rotation and back).
        No event is sent by default: the game must notice by itself."""
        size = self._window.get_size()
        self._window._dead = True
        self._window = Surface(size)
        if post_event:
            event.post(Event(WINDOWEXPOSED))


display = _Display()
