import os
import sys
import traceback

import pygame

import device
from anim import ease_out_cubic
from device import touch
from keyboard import OnScreenKeyboard
from scenes import SCENES
from theme import theme
from ui_objects import TextBox, dim_surface
from viewport import view

FPS = 30 if device.ANDROID else 60   # a phone has no use for more, and spends battery on it
# Seconds for a new screen to fade in. Every frame of a fade changes the whole picture, which is
# the most expensive kind of frame on a phone's big screen, so there it is kept short.
FADE_TIME = 0.1 if device.ANDROID else 0.2
AREA_HEIGHT = 600   # menus, lobby, join... are laid out in an area this tall (centred on taller screens)


class Game:

    def __init__(self, start_scene="menu"):
        # Not pygame.init(): that also starts the audio system, which this game never uses and
        # which prints errors on Android.
        pygame.display.init()
        pygame.font.init()
        pygame.key.set_repeat(400, 40)  # held keys repeat (e.g. backspace in text boxes)
        theme.load()                    # remember light/dark between runs
        touch.load()                    # ...and touch mode (same file, separate keys)

        self.canvas = view.open()       # viewport.py scales it into the real window
        self.size = view.size           # 800x600, or wider on a phone so it fills the screen
        pygame.display.set_caption("Uno - By Storm")
        self.clock = pygame.time.Clock()

        self.keyboard = OnScreenKeyboard(*self.size)   # the on-screen keyboard (touch mode)
        self.kb_armed = False                # the player tapped a text box, so it may show
        self._kb_box = None                  # the box it was last typing into (for sliding away)

        # Networking lives on Game so it survives scene changes.
        self.server = None   # only set while hosting
        self.client = None   # set while joining / in a lobby (the host has one too)
        self.notice = ""     # message for the next screen to show (e.g. "Host closed the lobby")

        self.running = True
        self.scene = None
        self.scene_name = start_scene
        self.fade_t = FADE_TIME
        self.change_scene(start_scene)

    def area_size(self, full: bool):
        """The size a screen is laid out in: the whole canvas (the game table) or a (width x 600)
        area (the other screens), which change_scene then centres on tall phone screens."""
        width, height = self.size
        return (width, height) if full else (width, min(height, AREA_HEIGHT))

    def change_scene(self, name: str):
        # A fresh scene object every time, so screens always start clean.
        self.scene_name = name
        self.scene = SCENES[name](self)
        area_h = self.scene.size[1]
        self.origin_y = 0 if area_h >= self.size[1] else (self.size[1] - area_h) // 3
        view.origin = (0, self.origin_y)
        self.fade_t = 0.0
        # A box that is focused when a screen opens must not pop the keyboard up by itself.
        self.kb_armed = False
        self._kb_box = None
        self.keyboard.t = 0.0
        view.lift = 0

    def disconnect(self, notice: str = ""):
        """Leave whatever lobby we're in and shut down the server if we were hosting."""
        if self.client:
            self.client.close()
            self.client = None
        if self.server:
            self.server.close()
            self.server = None
        self.notice = notice

    def quit(self):
        self.running = False

    def focused_box(self):
        """The text box being typed into right now, if any."""
        for obj in self.scene.objects:
            if isinstance(obj, TextBox) and obj.focused and obj.visible and obj.enabled:
                return obj
        return None

    # -------------------------------------------------------------- input

    def handle_event(self, event):
        view.note_event(event)
        if event.type == pygame.QUIT:
            self.quit()
        elif event.type == pygame.KEYDOWN and event.key == pygame.K_F2:
            theme.toggle()
        elif event.type == pygame.KEYDOWN and event.key == pygame.K_F3:
            touch.toggle()
        elif event.type == pygame.KEYDOWN and event.key == pygame.K_F4:
            view.cycle_window()                          # PC: next fixed window size
        else:
            event = view.convert_event(event)            # window pixels -> canvas pixels
            if touch.enabled:
                box = self.focused_box()
                used = self.keyboard.handle_event(event, box)
                if used == "hide":
                    self.kb_armed = False
                if used == "go":
                    self._go(box)
                if used:
                    return                               # the keyboard took it
            self.scene.handle_event(view.scene_event(event))   # canvas -> scene (lifted)
            if (touch.enabled and event.type == pygame.MOUSEBUTTONDOWN
                    and event.button == 1):
                # A tap on a text box brings the keyboard up; a tap anywhere else puts it away.
                self.kb_armed = self.focused_box() is not None

    def _go(self, box):
        """The keyboard's Go key: press Enter in the box. Done typing? Put the keyboard away."""
        if box is None:
            self.kb_armed = False
            return
        scene = self.scene
        box.submit()
        if self.scene is scene and self.focused_box() is box:
            self.kb_armed = False        # focus stayed put: this was the last box

    # -------------------------------------------------------------- one frame

    def step(self, dt: float):
        """One frame: network, then logic, then drawing."""
        # Network first, so scenes always see the latest state.
        if self.server:
            self.server.update()
        if self.client:
            self.client.update()

        if view.poll():                  # the window changed shape (a phone was rotated, say):
            self._rebuild()              # the canvas is new, so lay every screen out again

        view.touch = touch.enabled
        self.scene.update(dt)
        self.canvas.fill(self.scene.background())
        if self.origin_y == 0 and self.scene.size == self.size:
            self.scene.draw(self.canvas)
        else:                            # a screen with its own area: draw it centred
            area = pygame.Rect(0, self.origin_y, *self.scene.size)
            self.scene.draw(self.canvas.subsurface(area))

        if self.fade_t < FADE_TIME:  # new screens fade in from their own background color
            self.fade_t += dt
            veil = dim_surface(self.size, self.scene.background())
            veil.set_alpha(int(255 * (1 - ease_out_cubic(self.fade_t / FADE_TIME))))
            self.canvas.blit(veil, (0, 0))

        # On-screen keyboard: slide the picture up so the box stays visible, draw it on top.
        box = self.focused_box() if touch.enabled else None
        if box is not None:
            self._kb_box = box
        shown = touch.enabled and self.kb_armed and box is not None
        self.keyboard.update(dt, box, shown)
        view.lift = self.keyboard.lift_for(self._kb_box, self.origin_y)
        if self.keyboard.t == 0.0:
            self._kb_box = None
        view.apply_lift()
        self.keyboard.draw(self.canvas, self._kb_box)

    def _rebuild(self):
        """The screen changed shape (rotation): new canvas, new keyboard, same screen again."""
        self.canvas = view.canvas
        self.size = view.size
        self.keyboard = OnScreenKeyboard(*self.size)
        self.change_scene(self.scene_name)

    def run(self):
        while self.running:
            # Capped so a hiccup (e.g. dragging the window) doesn't make animations jump.
            dt = min(self.clock.tick(FPS) / 1000, 0.05)
            for event in pygame.event.get():
                self.handle_event(event)
            self.step(dt)
            view.present()

        self.disconnect()
        pygame.quit()


def _show_crash(text):
    """A packaged app has no console, so a crash would just vanish. Save it and put it on screen."""
    try:
        import settings
        folder = os.path.dirname(settings.SETTINGS_FILE)
        with open(os.path.join(folder, "crash.log"), "w", encoding="utf-8") as f:
            f.write(text)
    except Exception:
        pass
    try:
        pygame.display.init()
        pygame.font.init()
        screen = pygame.display.get_surface() or pygame.display.set_mode((0, 0) if device.ANDROID else (800, 600))
        font = pygame.font.Font(None, 24)
        screen.fill((30, 0, 0))
        y = 10
        try:
            from viewport import view
            text += "\n--- display log ---\n" + "\n".join(view.events[-12:])
        except Exception:
            pass
        for raw in ("The game crashed. This was saved to crash.log:", "") + tuple(text.splitlines()[-30:]):
            screen.blit(font.render(raw[:90], True, (255, 220, 220)), (10, y))
            y += 26
        pygame.display.flip()
        end = pygame.time.get_ticks() + 60000     # leave it up for a minute so it can be read
        while pygame.time.get_ticks() < end:
            if any(e.type in (pygame.QUIT, pygame.MOUSEBUTTONDOWN, pygame.KEYDOWN) for e in pygame.event.get()):
                break
            pygame.time.wait(50)
    except Exception:
        pass


if __name__ == "__main__":
    if "--selftest" in sys.argv:          # headless check that a packaged build works
        import selftest
        sys.exit(selftest.run(Game))
    # Dev shortcut: "python main.py join" starts directly on the join screen.
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    try:
        Game(start_scene=args[0] if args else "menu").run()
    except Exception:
        _show_crash(traceback.format_exc())
        raise
