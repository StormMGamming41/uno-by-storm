"""Small animation helpers: easing, cards flying across the table, confetti."""

import math
import random

import pygame


def clamp(x, lo=0.0, hi=1.0):
    return lo if x < lo else hi if x > hi else x


def lerp(a, b, t):
    return a + (b - a) * t


def lerp_color(c1, c2, t):
    t = clamp(t)
    return tuple(int(round(lerp(a, b, t))) for a, b in zip(c1, c2))


def ease_out_cubic(t):
    t = clamp(t)
    return 1 - (1 - t) ** 3


def approach(value, target, dt, rate=12.0):
    """Move `value` toward `target`, smoothly and independent of frame rate."""
    value += (target - value) * min(1.0, dt * rate)
    return target if abs(value - target) < 0.01 else value


class Flight:
    """
    A card (or a card back, when card is None) flying from `start` to `end`.
    `end` may be a function returning the current target, for targets that move
    (like a slot in your hand). `delay` staggers several flights. `on_land` runs once.
    """

    def __init__(self, card, start, end, duration=0.35, delay=0.0, on_land=None):
        self.card = card
        self.start = start
        self.end = end
        self.duration = duration
        self.t = -delay
        self.on_land = on_land
        self.landed = False
        self._last_end = start

    def _target(self):
        if callable(self.end):
            value = self.end()
            if value is not None:
                self._last_end = value
        else:
            self._last_end = self.end
        return self._last_end

    def update(self, dt):
        self.t += dt
        if self.t >= self.duration and not self.landed:
            self.landed = True
            if self.on_land:
                self.on_land()

    def position(self):
        """Where to draw the card right now, or None if it hasn't taken off / has landed."""
        if self.t < 0 or self.landed:
            return None
        p = ease_out_cubic(self.t / self.duration)
        ex, ey = self._target()
        x = lerp(self.start[0], ex, p)
        y = lerp(self.start[1], ey, p) - math.sin(math.pi * p) * 18  # a little arc
        return int(x), int(y)


class Confetti:
    COLORS = [(220, 50, 50), (240, 190, 30), (50, 160, 80), (40, 100, 220), (255, 255, 255)]

    def __init__(self, width, height, count=90, seed=0):
        rng = random.Random(seed)
        self.height = height
        self.t = 0.0
        # [x, y, fall speed, sway speed, phase, w, h, color]; they start above the screen
        # at different heights so they rain down gradually instead of all at once.
        self.bits = [[rng.uniform(0, width), rng.uniform(-height * 0.8, 0), rng.uniform(120, 260),
                      rng.uniform(1.5, 4), rng.uniform(0, 6.28), rng.randint(6, 10),
                      rng.randint(4, 8), rng.choice(self.COLORS)] for _ in range(count)]

    def update(self, dt):
        self.t += dt
        for b in self.bits:
            b[1] += b[2] * dt

    def draw(self, screen):
        for x, y, _, sway, phase, w, h, color in self.bits:
            if 0 <= y <= self.height:
                pygame.draw.rect(screen, color, (x + math.sin(self.t * sway + phase) * 18, y, w, h))
