import math
import os

import pygame

import clipboard
from anim import approach, lerp_color
from theme import theme
from viewport import pointer_pos

# Put Monocraft.ttf in an "assets" folder next to this file.
# If it's missing, pygame's default font is used so the game still runs.
ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
FONT_PATH = os.path.join(ASSET_DIR, "Monocraft.ttf")

COLOR_RGB = {
    "red": (220, 50, 50),
    "yellow": (240, 190, 30),
    "green": (50, 160, 80),
    "blue": (40, 100, 220),
    "wild": (30, 30, 30),
}

# ---------------------------------------------------------------- caches
# Rendering text and building card pictures is the expensive part of a frame, so each
# distinct thing is built once and reused. (Color is part of the key, so switching theme
# simply produces - and caches - the other color's version.)

_font_cache = {}
_text_cache = {}
_fit_cache = {}
_dim_cache = {}


def get_font(size: int, path: str = FONT_PATH) -> pygame.font.Font:
    """Fonts are created once per (path, size) and reused everywhere."""
    key = (path, size)
    if key not in _font_cache:
        if os.path.exists(path):
            _font_cache[key] = pygame.font.Font(path, size)
        else:
            _font_cache[key] = pygame.font.Font(None, size)
    return _font_cache[key]


def text_surface(text, size, color):
    """A rendered line of text. `color` must be an (r, g, b) tuple."""
    key = (text, size, color)
    surf = _text_cache.get(key)
    if surf is None:
        if len(_text_cache) > 800:
            _text_cache.clear()  # unbounded growth guard (e.g. lots of unique chat/names)
        surf = _text_cache[key] = get_font(size).render(text, True, color)
    return surf


def fit_text(text, size, max_width):
    """`text`, shortened with "..." if it would be wider than max_width pixels."""
    key = (text, size, max_width)
    cached = _fit_cache.get(key)
    if cached is not None:
        return cached
    font = get_font(size)
    result = text
    if font.size(text)[0] > max_width:
        while result and font.size(result + "...")[0] > max_width:
            result = result[:-1]
        result += "..."
    if len(_fit_cache) > 400:
        _fit_cache.clear()
    _fit_cache[key] = result
    return result


def wrap_text(text, size, max_width):
    """Split `text` into lines no wider than max_width pixels (words are never cut)."""
    font = get_font(size)
    lines = []
    for paragraph in str(text).split("\n"):
        line = ""
        for word in paragraph.split():
            trial = f"{line} {word}".strip()
            if line and font.size(trial)[0] > max_width:
                lines.append(line)
                line = word
            else:
                line = trial
        lines.append(line)
    return lines


def dim_surface(size, color=(0, 0, 0)):
    """A reusable solid surface for fades and dimming; set_alpha() it before blitting."""
    key = (tuple(size), tuple(color))
    surf = _dim_cache.get(key)
    if surf is None:
        if len(_dim_cache) > 16:
            _dim_cache.clear()
        surf = pygame.Surface(size)
        surf.fill(color)
        _dim_cache[key] = surf
    return surf


def _fast(surface):
    """Convert to the display's pixel format so blitting it every frame is cheap."""
    try:
        return surface.convert_alpha()
    except pygame.error:
        return surface


def luminance(color):
    r, g, b = color[:3]
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255


# ---------------------------------------------------------------- basics

class UIObject:
    """Base class: everything on screen has a rect and the same 3 methods."""

    def __init__(self, pos, size):
        self.rect = pygame.Rect(pos, size)
        self.visible = True
        self.enabled = True

    def handle_event(self, event):
        pass

    def update(self, dt: float):
        pass

    def draw(self, screen):
        pass


class Label(UIObject):
    """
    Text that can be placed anywhere. `color` is a theme role ("text", "muted", "error"...)
    or an (r, g, b) tuple; roles follow the light/dark theme automatically.
    """

    def __init__(self, pos, text="", size=24, color="text", center=False):
        super().__init__(pos, (0, 0))
        self._size = size
        self._color = color
        self._center = center
        self._anchor = pos
        self._text = str(text)
        self._layout()

    def _layout(self):
        # " " instead of "" so an empty label never produces a zero-width box
        w, h = get_font(self._size).size(self._text or " ")
        self.rect = pygame.Rect(0, 0, w, h)
        if self._center:
            self.rect.center = self._anchor
        else:
            self.rect.topleft = self._anchor

    @property
    def text(self):
        return self._text

    @text.setter
    def text(self, value):
        value = str(value)
        if value != self._text:
            self._text = value
            self._layout()

    @property
    def color(self):
        return self._color

    @color.setter
    def color(self, value):
        self._color = value

    def draw(self, screen):
        if self._text:
            screen.blit(text_surface(self._text, self._size, theme.resolve(self._color)), self.rect)


class TextBlock(UIObject):
    """
    Several lines of wrapped text. Like Label, `text` and `color` can be changed any time
    (color is a theme role or an (r, g, b) tuple). The block grows downward from `pos`.
    """

    def __init__(self, pos, width, text="", size=18, color="text", center=False, line_gap=4):
        super().__init__(pos, (width, 0))
        self._size = size
        self._color = color
        self._center = center
        self._gap = line_gap
        self._text = None
        self._lines = []
        self.text = text

    @property
    def text(self):
        return self._text

    @text.setter
    def text(self, value):
        value = str(value)
        if value != self._text:
            self._text = value
            self._lines = wrap_text(value, self._size, self.rect.width) if value else []
            self.rect.height = len(self._lines) * (get_font(self._size).get_height() + self._gap)

    @property
    def color(self):
        return self._color

    @color.setter
    def color(self, value):
        self._color = value

    def draw(self, screen):
        color = theme.resolve(self._color)
        step = get_font(self._size).get_height() + self._gap
        for i, line in enumerate(self._lines):
            if not line:
                continue
            surf = text_surface(line, self._size, color)
            pos = (self.rect.centerx - surf.get_width() // 2 if self._center else self.rect.x,
                   self.rect.y + i * step)
            screen.blit(surf, pos)


class Panel(UIObject):
    """A rounded card to group things on. Purely decorative."""

    def __init__(self, pos, size, role="panel", radius=14):
        super().__init__(pos, size)
        self.role = role
        self.radius = radius

    def draw(self, screen):
        pygame.draw.rect(screen, theme[self.role], self.rect, border_radius=self.radius)
        pygame.draw.rect(screen, theme["border"], self.rect, width=1, border_radius=self.radius)


class Button(UIObject):
    """
    A clickable button that eases to a hover color, lifts slightly, and presses down.
    `color` is a theme role (e.g. "btn_green") or an (r, g, b) tuple. Text color is chosen
    automatically for contrast unless `text_color` is given.
    """

    def __init__(self, pos, size, text="Button", text_size=20, color="btn_neutral",
                 hover_color=None, text_color=None, border_radius=10,
                 action=None, args=(), kwargs=None):
        super().__init__(pos, size)
        self.text = text
        self.text_size = text_size
        self.color = color
        self.hover_color = hover_color
        self.text_color = text_color
        self.border_radius = max(0, border_radius)
        self.action = action
        self.args = args
        self.kwargs = kwargs or {}
        self.hover_t = 0.0   # 0..1, how "hovered" the button currently looks
        self.pressed = False

    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.pressed = self.rect.collidepoint(event.pos)
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self.pressed and self.rect.collidepoint(event.pos) and self.action:
                self.action(*self.args, **self.kwargs)
            self.pressed = False

    def update(self, dt: float):
        hovered = self.rect.collidepoint(pointer_pos())
        self.hover_t = approach(self.hover_t, 1.0 if hovered else 0.0, dt, 18)

    def draw(self, screen):
        radius = self.border_radius
        if self.enabled:
            base = theme.resolve(self.color)
            if self.hover_color is not None:
                target = theme.resolve(self.hover_color)
            elif luminance(base) > 0.6:
                target = lerp_color(base, (0, 0, 0), 0.12)
            else:
                target = lerp_color(base, (255, 255, 255), 0.14)
            fill = lerp_color(base, target, self.hover_t)
            text_color = (theme.resolve(self.text_color) if self.text_color is not None
                          else ((20, 22, 30) if luminance(base) > 0.6 else (255, 255, 255)))
            lift = 0 if self.pressed else round(2 * self.hover_t)
            pygame.draw.rect(screen, theme["shadow"], self.rect.move(0, 3), border_radius=radius)
            face = self.rect.move(0, 1 if self.pressed else -lift)
        else:
            fill, text_color = theme["disabled"], theme["disabled_text"]
            face = self.rect
        pygame.draw.rect(screen, fill, face, border_radius=radius)

        label = text_surface(fit_text(self.text, self.text_size, face.width - 16),
                             self.text_size, text_color)
        screen.blit(label, label.get_rect(center=face.center))


class TextBox(UIObject):
    """
    Single-line text input. Click to focus, click elsewhere to unfocus.
    Characters not in `allowed` are silently discarded (allowed=None accepts any printable).
    """

    PAD = 12

    def __init__(self, pos, size, text="", text_size=24, allowed=None, max_length=32,
                 placeholder="", on_submit=None):
        super().__init__(pos, size)
        self.text_size = text_size
        self.allowed = set(allowed) if allowed is not None else None
        self.max_length = max_length
        self.placeholder = placeholder
        self.on_submit = on_submit  # called when Enter is pressed
        self.focused = False

        self._blink = 0.0
        self._text = ""
        self.text = text

    def accepts(self, ch: str) -> bool:
        """Would this box keep the character `ch`? (The on-screen keyboard greys out the rest.)"""
        return ch.isprintable() and (self.allowed is None or ch in self.allowed)

    _accepts = accepts

    @property
    def text(self):
        return self._text

    @text.setter
    def text(self, value):
        self._text = "".join(ch for ch in str(value) if self._accepts(ch))[: self.max_length]

    # What typing does. The keyboard on the real keyboard and the on-screen one share these.

    def insert(self, text: str) -> bool:
        """Add text at the end (anything the box doesn't accept is dropped). True if it grew."""
        before = len(self._text)
        self.text = self._text + text
        self._blink = 0.0
        return len(self._text) > before

    def backspace(self):
        self.text = self._text[:-1]
        self._blink = 0.0

    def submit(self):
        if self.on_submit:
            self.on_submit()

    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.focused = self.rect.collidepoint(event.pos)
            self._blink = 0.0
        elif event.type == pygame.KEYDOWN and self.focused:
            self._blink = 0.0
            if event.key == pygame.K_v and getattr(event, "mod", 0) & (pygame.KMOD_CTRL | pygame.KMOD_META):
                self.insert(clipboard.paste())   # the box filters out anything it doesn't accept
            elif event.key == pygame.K_BACKSPACE:
                self.backspace()
            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.submit()
            elif event.unicode and self.accepts(event.unicode):
                self.insert(event.unicode)

    def update(self, dt: float):
        self._blink = (self._blink + dt) % 1.0

    def draw(self, screen):
        border = theme["accent"] if self.focused else theme["border"]
        pygame.draw.rect(screen, theme["input"], self.rect, border_radius=8)
        pygame.draw.rect(screen, border, self.rect, width=2, border_radius=8)

        inner_w = self.rect.width - 2 * self.PAD
        text_h = get_font(self.text_size).get_height()
        x = self.rect.x + self.PAD
        y = self.rect.centery - text_h // 2
        cursor_x = x

        if self._text:
            surf = text_surface(self._text, self.text_size, theme["text"])
            w = surf.get_width()
            if w > inner_w:  # too long to fit: show the end of the text
                area = pygame.Rect(w - inner_w, 0, inner_w, surf.get_height())
                screen.blit(surf, (x, y), area)
                cursor_x = x + inner_w
            else:
                screen.blit(surf, (x, y))
                cursor_x = x + w
        elif self.placeholder:
            screen.blit(text_surface(self.placeholder, self.text_size, theme["muted"]), (x, y))

        if self.focused and self._blink < 0.5:
            pygame.draw.line(screen, theme["text"], (cursor_x + 2, y), (cursor_x + 2, y + text_h), 2)


class Checkbox(UIObject):
    """A tick box with a label. Read `.checked`."""

    def __init__(self, pos, width, text, checked=True, size=20):
        super().__init__(pos, (width, 28))
        self.text = text
        self.size = size
        self.checked = checked
        self.hover_t = 0.0

    def handle_event(self, event):
        if (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
                and self.rect.collidepoint(event.pos)):
            self.checked = not self.checked

    def update(self, dt: float):
        hovered = self.rect.collidepoint(pointer_pos())
        self.hover_t = approach(self.hover_t, 1.0 if hovered else 0.0, dt, 18)

    def draw(self, screen):
        box = pygame.Rect(self.rect.x, self.rect.y + 2, 24, 24)
        pygame.draw.rect(screen, theme["accent"] if self.checked else theme["input"], box,
                         border_radius=6)
        pygame.draw.rect(screen, lerp_color(theme["border"], theme["accent"], self.hover_t), box,
                         width=2, border_radius=6)
        if self.checked:
            x, y = box.x, box.y
            pygame.draw.line(screen, (255, 255, 255), (x + 5, y + 12), (x + 10, y + 17), 3)
            pygame.draw.line(screen, (255, 255, 255), (x + 10, y + 17), (x + 19, y + 7), 3)
        label = text_surface(fit_text(self.text, self.size, self.rect.width - 36), self.size,
                             theme["text"])
        screen.blit(label, label.get_rect(midleft=(box.right + 12, box.centery)))


class Tabs(UIObject):
    """A switch between a few options, like [ Room code | Address ]."""

    def __init__(self, pos, size, options, selected=0, on_change=None, text_size=20):
        super().__init__(pos, size)
        self.options = list(options)
        self.selected = selected
        self.on_change = on_change
        self.text_size = text_size

    def _segment(self, i):
        w = self.rect.width // len(self.options)
        return pygame.Rect(self.rect.x + i * w, self.rect.y, w, self.rect.height)

    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for i in range(len(self.options)):
                if self._segment(i).collidepoint(event.pos) and i != self.selected:
                    self.selected = i
                    if self.on_change:
                        self.on_change(i)

    def draw(self, screen):
        pygame.draw.rect(screen, theme["panel_alt"], self.rect, border_radius=10)
        for i, name in enumerate(self.options):
            seg = self._segment(i)
            on = i == self.selected
            if on:
                pygame.draw.rect(screen, theme["accent"], seg.inflate(-6, -6), border_radius=8)
            label = text_surface(name, self.text_size, (255, 255, 255) if on else theme["muted"])
            screen.blit(label, label.get_rect(center=seg.center))


class ThemeToggle(UIObject):
    """Round sun/moon button that flips between light and dark mode."""

    def __init__(self, pos, size=44):
        super().__init__(pos, (size, size))
        self.hover_t = 0.0

    def handle_event(self, event):
        if (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
                and self.rect.collidepoint(event.pos)):
            theme.toggle()

    def update(self, dt: float):
        hovered = self.rect.collidepoint(pointer_pos())
        self.hover_t = approach(self.hover_t, 1.0 if hovered else 0.0, dt, 18)

    def draw(self, screen):
        cx, cy = self.rect.center
        r = self.rect.width // 2
        pygame.draw.circle(screen, theme["shadow"], (cx, cy + 2), r)
        pygame.draw.circle(screen, lerp_color(theme["panel"], theme["panel_alt"], self.hover_t),
                           (cx, cy), r)
        pygame.draw.circle(screen, theme["border"], (cx, cy), r, 1)
        gold = (245, 192, 45)
        if theme.is_dark:  # currently dark -> show a sun (click for light)
            pygame.draw.circle(screen, gold, (cx, cy), 6)
            for i in range(8):
                a = i * math.pi / 4
                pygame.draw.line(screen, gold,
                                 (cx + math.cos(a) * 10, cy + math.sin(a) * 10),
                                 (cx + math.cos(a) * 14, cy + math.sin(a) * 14), 2)
        else:              # currently light -> show a moon (click for dark)
            pygame.draw.circle(screen, (95, 105, 140), (cx, cy), 10)
            pygame.draw.circle(screen, lerp_color(theme["panel"], theme["panel_alt"], self.hover_t),
                               (cx + 5, cy - 4), 9)


class Logo(UIObject):
    """The UNO title: three colored tiles that gently bob up and down."""

    TILES = (("U", "red"), ("N", "yellow"), ("O", "blue"))

    def __init__(self, center, tile=(76, 96), gap=14):
        width = 3 * tile[0] + 2 * gap
        super().__init__((center[0] - width // 2, center[1] - tile[1] // 2), (width, tile[1]))
        self.tile = tile
        self.gap = gap
        self.t = 0.0

    def update(self, dt: float):
        self.t += dt

    def draw(self, screen):
        tw, th = self.tile
        for i, (letter, color) in enumerate(self.TILES):
            bob = math.sin(self.t * 2.2 + i * 0.9) * 5
            r = pygame.Rect(self.rect.x + i * (tw + self.gap), int(self.rect.y + bob), tw, th)
            pygame.draw.rect(screen, theme["shadow"], r.move(0, 7), border_radius=16)
            pygame.draw.rect(screen, (255, 255, 255), r, border_radius=16)
            pygame.draw.rect(screen, COLOR_RGB[color], r.inflate(-10, -10), border_radius=12)
            glyph = text_surface(letter, 84, (255, 255, 255))
            screen.blit(glyph, glyph.get_rect(center=r.center))


class Leaderboard(UIObject):
    """
    The lobby's player table: rank, name, points and wins, best player first.
    Ties share a rank. Before anyone has played a game the rank column shows "-".
    Call set_players() every frame with the lobby's player dicts; it only recomputes on change.
    """

    HEADER_H = 32
    MEDALS = {1: (245, 192, 45), 2: (186, 192, 204), 3: (205, 127, 50)}

    def __init__(self, pos, size, row_height=28, text_size=22):
        super().__init__(pos, size)
        self.row_height = row_height
        self.text_size = text_size
        self._key = None
        self.rows = []   # [{"id", "rank", "name", "points", "wins"}] - handy for tests too

    def set_players(self, players, my_id):
        key = (my_id, tuple((p.get("id"), p.get("name"), p.get("host"), p.get("points", 0),
                             p.get("wins", 0), p.get("games", 0)) for p in players))
        if key == self._key:
            return
        self._key = key

        played = any(p.get("games", 0) for p in players)
        ranked = sorted(players, key=lambda p: (-p.get("points", 0), -p.get("wins", 0)))
        self.rows = []
        for p in ranked:
            points, wins = p.get("points", 0), p.get("wins", 0)
            # ties share the rank of the first player with the same numbers
            rank = next(j for j, q in enumerate(ranked)
                        if (q.get("points", 0), q.get("wins", 0)) == (points, wins)) + 1
            name = str(p.get("name", "?"))
            if p.get("host") and name.casefold() != "host":
                name += " (Leader)"
            if p.get("id") == my_id:
                name += " (You)"
            self.rows.append({"id": p.get("id"), "rank": rank if played else None,
                              "name": name, "points": points, "wins": wins})

    def draw(self, screen):
        r = self.rect
        size = self.text_size
        pygame.draw.rect(screen, theme["panel"], r, border_radius=12)
        pygame.draw.rect(screen, theme["border"], r, width=1, border_radius=12)

        right_pts, right_wins = r.right - 110, r.right - 24
        mid = r.y + self.HEADER_H // 2
        for text, x, side in (("#", r.x + 18, "midleft"), ("Player", r.x + 60, "midleft"),
                              ("Pts", right_pts, "midright"), ("Wins", right_wins, "midright")):
            surf = text_surface(text, size - 2, theme["muted"])
            screen.blit(surf, surf.get_rect(**{side: (x, mid)}))
        pygame.draw.line(screen, theme["border"], (r.x + 12, r.y + self.HEADER_H),
                         (r.right - 12, r.y + self.HEADER_H), 2)

        y = r.y + self.HEADER_H + 4
        for row in self.rows:
            if y + self.row_height > r.bottom:
                break
            cy = y + self.row_height // 2
            leader = row["rank"] == 1
            if leader:
                pygame.draw.rect(screen, theme["highlight"],
                                 (r.x + 8, y, r.width - 16, self.row_height), border_radius=8)
            if row["rank"] in self.MEDALS:
                pygame.draw.circle(screen, self.MEDALS[row["rank"]], (r.x + 26, cy), 11)
                num = text_surface(str(row["rank"]), size - 2, (40, 30, 10))
            else:
                num = text_surface("-" if row["rank"] is None else str(row["rank"]),
                                   size - 2, theme["muted"])
            screen.blit(num, num.get_rect(center=(r.x + 26, cy)))

            name = text_surface(fit_text(row["name"], size, right_pts - (r.x + 60) - 50),
                                size, theme["text"])
            screen.blit(name, name.get_rect(midleft=(r.x + 60, cy)))
            pts = text_surface(str(row["points"]), size, theme["text"])
            screen.blit(pts, pts.get_rect(midright=(right_pts, cy)))
            wins = text_surface(str(row["wins"]), size, theme["muted"])
            screen.blit(wins, wins.get_rect(midright=(right_wins, cy)))
            y += self.row_height


# ---------------------------------------------------------------- cards

CARD_TEXT = {"skip": "SKIP", "reverse": "REV", "draw2": "+2", "wild": "WILD", "wild4": "+4"}
_card_cache = {}
_shadow_cache = {}


def _paint_card(surface, rect, card, dim):
    """Draw one card face (or the back, if card is None) onto `surface`."""
    pygame.draw.rect(surface, (255, 255, 255), rect, border_radius=8)
    inner = rect.inflate(-8, -8)

    if card is None:
        pygame.draw.rect(surface, (25, 25, 30), inner, border_radius=6)
        pygame.draw.ellipse(surface, COLOR_RGB["red"], inner.inflate(-10, -34))
        logo = text_surface("UNO", max(14, rect.height // 4), (255, 215, 60))
        surface.blit(logo, logo.get_rect(center=rect.center))
        return

    color, value = card["color"], card["value"]
    text = CARD_TEXT.get(value, value)
    big = len(text) <= 2
    if color == "wild":
        pygame.draw.rect(surface, COLOR_RGB["wild"], inner, border_radius=6)
        block = pygame.Rect(0, 0, int(inner.width * 0.7), int(inner.height * 0.42))
        block.center = (inner.centerx, inner.centery + int(inner.height * 0.12))
        half_w, half_h = block.width // 2, block.height // 2
        for i, c in enumerate(("red", "yellow", "green", "blue")):
            quad = pygame.Rect(block.x + (i % 2) * half_w, block.y + (i // 2) * half_h,
                               half_w, half_h)
            pygame.draw.rect(surface, COLOR_RGB[c], quad)
        label = text_surface(text, int(rect.height * (0.28 if big else 0.2)), (255, 255, 255))
        surface.blit(label, label.get_rect(center=(inner.centerx, inner.y + int(inner.height * 0.2))))
    else:
        rgb = COLOR_RGB[color]
        pygame.draw.rect(surface, rgb, inner, border_radius=6)
        pygame.draw.ellipse(surface, (255, 255, 255),
                            inner.inflate(-int(inner.width * 0.25), -int(inner.height * 0.35)))
        label = text_surface(text, int(rect.height * (0.36 if big else 0.2)), rgb)
        surface.blit(label, label.get_rect(center=inner.center))
        corner = text_surface(text, int(rect.height * 0.17), (255, 255, 255))
        surface.blit(corner, (inner.x + 4, inner.y + 2))

    if dim:
        shade = pygame.Surface(rect.size, pygame.SRCALPHA)
        pygame.draw.rect(shade, (0, 0, 0, 130), shade.get_rect(), border_radius=8)
        surface.blit(shade, (0, 0))


def card_surface(card, size, dim=False):
    """The picture of a card, built once and reused every frame."""
    key = ("back", size) if card is None else (card["color"], card["value"], size, dim)
    surf = _card_cache.get(key)
    if surf is None:
        surf = pygame.Surface(size, pygame.SRCALPHA)
        _paint_card(surf, pygame.Rect(0, 0, *size), card, dim)
        surf = _card_cache[key] = _fast(surf)
    return surf


def _card_shadow(size):
    surf = _shadow_cache.get(size)
    if surf is None:
        surf = pygame.Surface(size, pygame.SRCALPHA)
        pygame.draw.rect(surf, (0, 0, 0, 70), surf.get_rect(), border_radius=8)
        surf = _shadow_cache[size] = _fast(surf)
    return surf


def draw_card(screen, rect, card=None, dim=False, shadow=False):
    """
    Draw one UNO card. `card` is the dict the server sends ({"color", "value", ...});
    pass None to draw the back of a card. dim=True greys it out (can't be played).
    """
    size = (rect.width, rect.height)
    if shadow:
        screen.blit(_card_shadow(size), (rect.x + 3, rect.y + 4))
    screen.blit(card_surface(card, size, dim), rect.topleft)
