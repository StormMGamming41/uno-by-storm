"""
Light and dark color palettes.

UI code never hard-codes a color for anything that should change with the theme.
Instead it asks for a *role* by name ("text", "panel", "btn_green", ...) at draw time,
so flipping the theme changes the whole game instantly, without rebuilding any screen.

The choice is remembered through settings.py (settings.json next to the game files).
"""

import settings

PALETTES = {
    "light": {
        "bg": (240, 243, 249), "panel": (255, 255, 255), "panel_alt": (233, 237, 245),
        "border": (208, 214, 226), "shadow": (202, 208, 222),
        "text": (26, 30, 43), "muted": (105, 113, 132),
        "accent": (66, 133, 244), "error": (205, 45, 45), "ok": (28, 140, 70),
        "highlight": (255, 239, 176), "highlight_text": (125, 85, 0),
        "input": (255, 255, 255), "disabled": (210, 214, 224), "disabled_text": (150, 156, 172),
        "table": (44, 122, 88), "table_text": (255, 255, 255), "table_muted": (196, 226, 208),
        "box": (252, 252, 252), "toast": (255, 205, 205),
        "btn_neutral": (220, 224, 234), "btn_blue": (66, 125, 232), "btn_green": (46, 170, 96),
        "btn_red": (234, 82, 82), "btn_yellow": (245, 192, 45),
    },
    "dark": {
        "bg": (17, 19, 29), "panel": (28, 31, 45), "panel_alt": (38, 42, 60),
        "border": (58, 63, 86), "shadow": (8, 9, 15),
        "text": (235, 238, 246), "muted": (146, 153, 175),
        "accent": (102, 163, 255), "error": (255, 122, 122), "ok": (112, 222, 142),
        "highlight": (86, 72, 28), "highlight_text": (255, 222, 120),
        "input": (22, 25, 38), "disabled": (44, 48, 64), "disabled_text": (100, 106, 126),
        "table": (15, 54, 41), "table_text": (255, 255, 255), "table_muted": (160, 190, 175),
        "box": (32, 36, 52), "toast": (255, 170, 170),
        "btn_neutral": (58, 63, 84), "btn_blue": (66, 112, 210), "btn_green": (44, 150, 88),
        "btn_red": (210, 70, 70), "btn_yellow": (222, 174, 38),
    },
}


class Theme:
    def __init__(self):
        self.name = "light"

    @property
    def is_dark(self) -> bool:
        return self.name == "dark"

    def __getitem__(self, role: str):
        return PALETTES[self.name][role]

    def resolve(self, spec):
        """A role name ("panel") or an (r, g, b) tuple -> an (r, g, b) tuple."""
        return PALETTES[self.name][spec] if isinstance(spec, str) else tuple(spec)

    def set(self, name: str, save: bool = True):
        if name in PALETTES:
            self.name = name
            if save:
                self.save()

    def toggle(self):
        self.set("light" if self.is_dark else "dark")

    def load(self):
        self.set(str(settings.get("theme", "light")), save=False)  # unknown name: ignored

    def save(self):
        settings.save(theme=self.name)   # only the "theme" key; other settings are kept


theme = Theme()
