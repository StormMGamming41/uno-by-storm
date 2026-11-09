"""Helpers for driving the game under the stand-in pygame (see tests/fake/pygame)."""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "fake"))
sys.path.insert(0, os.path.dirname(HERE))
import pygame
import viewport as _vp
_vp.STABLE_STEP_MS = 0     # tests don't need to really wait for the screen to settle

def tap(game, x, y, frames=2, dt=0.034):
    """A tap at WINDOW pixel (x, y): move, press, release, with frames in between."""
    pygame.mouse.pos = (x, y)
    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(x, y), button=1))
    run(game, 1, dt)
    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONUP, pos=(x, y), button=1))
    run(game, frames, dt)

def run(game, n=1, dt=0.034):
    from viewport import view
    for _ in range(n):
        for e in pygame.event.get():
            game.handle_event(e)
        game.step(dt)
        view.present()

def shot(name):
    os.makedirs(os.path.join(HERE, "shots"), exist_ok=True)
    pygame.display._screen.save(os.path.join(HERE, "shots", name + ".png"))

def canvas_to_window(x, y):
    from viewport import view
    return (view.dest.x + x * view.scale, view.dest.y + y * view.scale)
