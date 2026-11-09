"""
Opens the game's own window (same code as the game) and reports what's wrong with taps and typing.

    python check_display.py

Step 1: tap each numbered circle.   Step 2: type  uno:/1  with the on-screen keyboard
(it has : and / on the ?123 page).   Then it prints a report and saves check_display_report.txt.
Paste that report if something doesn't work. Nothing is sent over the network.
"""

import math
import sys
import time

import pygame

import clipboard
import device
from device import touch
from keyboard import OnScreenKeyboard
from theme import theme
from ui_objects import TextBox, text_surface
from viewport import view

TARGETS = []            # filled in once the window exists: four corners and the middle
PHRASE = "uno:/1"
MISS = 40               # a tap this far (canvas px) from a circle centre is a miss (radius is 28)
BIAS = 25               # all taps off the same way by this much (canvas px) = a mapping bug, not a shaky finger
EVENT_NAMES = {pygame.MOUSEBUTTONDOWN: "mouse down", pygame.MOUSEBUTTONUP: "mouse up",
               pygame.MOUSEMOTION: "mouse move", pygame.KEYDOWN: "key down",
               pygame.FINGERDOWN: "finger down", pygame.FINGERUP: "finger up"}


def main(max_seconds=300):
    pygame.display.init()
    pygame.font.init()
    theme.load()
    touch.load()
    touch.enabled = True          # this check is about touch
    canvas = view.open()
    w, h = view.size
    TARGETS[:] = [(60, 60), (w - 60, 60), (w // 2, 200), (60, h - 60), (w - 60, h - 60)]
    view.touch = True
    clock = pygame.time.Clock()
    kb = OnScreenKeyboard(w, h)
    box = TextBox((w // 2 - 200, 330), (400, 50), placeholder="type here", allowed=None, max_length=20)

    counts, taps, works, periods, offsets = {}, [], [], [], []
    hits = set()
    hw_keys = ""
    kb_armed, started, finished = False, time.time(), False

    while not finished and time.time() - started < max_seconds:
        view.poll()                         # notice rotation / a replaced window before drawing
        ms = clock.tick(30)                 # includes the wait that holds us to 30 fps
        periods.append(ms)
        t0 = time.perf_counter()            # from here on it is real work
        dt = min(ms / 1000, 0.05)
        for ev in pygame.event.get():
            view.note_event(ev)
            name = EVENT_NAMES.get(ev.type)
            if name:
                counts[name] = counts.get(name, 0) + 1
            if ev.type == pygame.QUIT or (ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE):
                finished = True
            if ev.type == pygame.KEYDOWN and getattr(ev, "unicode", ""):
                hw_keys += ev.unicode
            ev = view.convert_event(ev)
            if kb.handle_event(ev, box if box.focused else None):
                continue
            box.handle_event(ev)
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                kb_armed = box.focused
                best = min(range(len(TARGETS)), key=lambda i: math.dist(ev.pos, TARGETS[i]))
                err = math.dist(ev.pos, TARGETS[best])
                if err <= 60:
                    taps.append((best + 1, round(err)))
                    offsets.append((ev.pos[0] - TARGETS[best][0], ev.pos[1] - TARGETS[best][1]))
                    hits.add(best)

        kb.update(dt, box if box.focused else None, kb_armed and box.focused)
        view.lift = kb.lift_for(box)
        canvas.fill(theme["bg"])
        for i, (x, y) in enumerate(TARGETS):
            pygame.draw.circle(canvas, theme["ok"] if i in hits else theme["accent"], (x, y), 28)
            label = text_surface(str(i + 1), 26, (255, 255, 255))
            canvas.blit(label, label.get_rect(center=(x, y)))
        lines = ["Step 1: tap the 5 circles", "Step 2: tap the box, type   " + PHRASE,
                 "Esc or close the window to finish"]
        for n, line in enumerate(lines):
            surf = text_surface(line, 22, theme["text"])
            canvas.blit(surf, surf.get_rect(center=(w // 2, 250 + n * 26 - 130)))
        box.update(dt)
        box.draw(canvas)
        done = box.text == PHRASE and len(hits) == len(TARGETS)
        if done:
            surf = text_surface("All good - finishing...", 28, theme["ok"])
            canvas.blit(surf, surf.get_rect(center=(w // 2, 450)))
            finished = True
        view.apply_lift()
        kb.draw(canvas, box)
        view.present()
        works.append(time.perf_counter() - t0)
        if finished and done:
            time.sleep(0.6)

    return report(counts, taps, offsets, hits, box.text, hw_keys, works, periods)


def report(counts, taps, offsets, hits, typed, hw_keys, works, periods):
    info = pygame.display.get_surface().get_size()
    problems = []
    if not any(counts.get(k) for k in ("mouse down",)):
        if counts.get("finger down"):
            problems.append("Only finger events arrived, no mouse events. The game listens to mouse "
                            "events. In Termux:X11 set Preferences > Input > Touch mode to "
                            "'Simulated touchscreen'.")
        else:
            problems.append("No taps arrived at all. Is the Termux:X11 window focused?")
    elif len(hits) < len(TARGETS):
        problems.append(f"Only {len(hits)} of {len(TARGETS)} circles were tapped.")
    worst = max((e for _, e in taps), default=0)
    if offsets:
        bx = sum(o[0] for o in offsets) / len(offsets)
        by = sum(o[1] for o in offsets) / len(offsets)
        if max(abs(bx), abs(by)) > BIAS:
            problems.append(f"Taps are off the same way by about ({bx:+.0f}, {by:+.0f}) canvas px: "
                            "the picture scaling and the tap mapping disagree.")
    if worst > MISS:
        problems.append(f"One tap landed {worst} px from its circle: a miss, or a mapping problem.")
    if typed != PHRASE:
        problems.append(f"Typed text was {typed!r}, expected {PHRASE!r}. Keys ':' and '/' are on "
                        "the ?123 page.")
    warm = 5                                    # the first frames load fonts etc.: not counted
    w, p = works[warm:] or works, periods[warm:] or periods
    work = sum(w) / len(w) * 1000 if w else 0
    fps = 1000 / (sum(p) / len(p)) if p and sum(p) else 0
    if fps < 25:
        problems.append(f"Slow: {fps:.0f} frames a second (the game aims for 30; the work alone "
                        f"takes {work:.0f} ms a frame). Lower the Termux:X11 display resolution "
                        "(e.g. 1280x720).")
    out = ["UNO display check",
           f"  python {sys.version.split()[0]}, pygame {getattr(pygame.version, 'ver', '?')}, "
           f"android={device.ANDROID}, driver={pygame.display.get_driver()}",
           f"  screen: {'upright (portrait)' if info[1] > info[0] else 'sideways (landscape)'}; "
           f"termux={device.IN_TERMUX}",
           f"  window {info[0]}x{info[1]}, canvas {view.size[0]}x{view.size[1]}, picture {view.dest.w}x{view.dest.h} at "
           f"({view.dest.x},{view.dest.y}), scale {view.scale:.2f}, "
           f"{'smooth' if view.smooth else 'fast'} scaling ({view.scale_ms:.1f} ms)",
           f"  events: {counts or 'none'}",
           f"  taps: {taps or 'none'}  (circle number, px off)",
           f"  typed with on-screen keyboard: {typed!r}   hardware keys seen: {hw_keys!r}",
           f"  speed: {fps:.0f} frames/second, {work:.0f} ms of work per frame "
           f"(scaling {view.scale_ms:.1f} ms of that), {len(works)} frames",
           f"  sent to screen: {view.stats['skipped']} frames nothing, {view.stats['partial']} partial, "
           f"{view.stats['full']} full; display errors survived: {view.errors}"
           + (f"; {view.scale_note}" if view.scale_note else "")]
    if device.ANDROID:
        t0 = time.time()
        got = clipboard.paste()
        out.append(f"  clipboard: {'ok' if not clipboard.unavailable_reason else 'OFF - ' + clipboard.unavailable_reason}"
                   f" ({time.time() - t0:.1f} s, {len(got)} chars)")
    out.append("  display log (what the screen did, oldest first):")
    out += ["    " + line for line in view.events[-14:]]
    out.append("PROBLEMS:" if problems else "No problems found.")
    out += ["  - " + p for p in problems]
    text = "\n".join(out)
    print(text)
    try:
        with open("check_display_report.txt", "w", encoding="utf-8") as f:
            f.write(text + "\n")
    except OSError:
        pass
    pygame.quit()
    return not problems


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
