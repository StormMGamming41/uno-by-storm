"""
Copy and paste text, so a room code can be shared without retyping it.

Windows / Linux / macOS: pygame's own clipboard first (safe everywhere pygame runs), then
tkinter (ships with Python on Windows and Linux; skipped on macOS where it can clash with
pygame's window).

In Termux (development only): the Termux:API app's `termux-clipboard-set` / `termux-clipboard-get`
commands. Those commands are known to HANG (not fail) when the Termux:API app isn't installed,
so they run with a timeout, and after the first failure or timeout the clipboard is switched
off for the rest of the session instead of freezing the game again on every press.

Everything is wrapped so a missing or broken clipboard just returns False / "" instead of
ever crashing the game. `unavailable_reason` says why it stopped working (or "" if it hasn't).
"""

import shutil
import subprocess
import sys

import device

TERMUX_TIMEOUT = 4.0       # seconds to wait for the Termux:API app before giving up
unavailable_reason = ""    # set once the Android clipboard has failed; "" while it still works


def _use_tk() -> bool:
    return not sys.platform.startswith("darwin") and not device.ANDROID


def _termux_mode() -> bool:
    """Use the termux-clipboard commands only inside Termux. A packaged APK has no Termux and
    uses pygame's own clipboard (SDL's, which talks to Android's)."""
    return device.IN_TERMUX


def _termux(cmd, text=None):
    """Run a termux-clipboard command. -> (ok, stdout). On any failure, turns the clipboard off."""
    global unavailable_reason
    if unavailable_reason:
        return False, ""
    exe = shutil.which(cmd[0])
    if exe is None:
        unavailable_reason = f"{cmd[0]} is not installed (pkg install termux-api)"
        return False, ""
    try:
        done = subprocess.run([exe] + cmd[1:], input=text, capture_output=True, text=True,
                              timeout=TERMUX_TIMEOUT, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        unavailable_reason = "the Termux:API app did not answer (is it installed?)"
        return False, ""
    except OSError as problem:
        unavailable_reason = f"{cmd[0]} could not run: {problem}"
        return False, ""
    if done.returncode != 0:
        unavailable_reason = f"{cmd[0]} failed: {(done.stderr or '').strip()[:80]}"
        return False, ""
    return True, done.stdout or ""


def copy(text: str) -> bool:
    """Put text on the clipboard. Returns True if it worked."""
    if _termux_mode():
        return _termux(["termux-clipboard-set"], text)[0]
    try:
        import pygame
        pygame.scrap.init()
        pygame.scrap.put(pygame.SCRAP_TEXT, text.encode("utf-8"))
        return True
    except Exception:
        pass
    if _use_tk():
        try:
            import tkinter
            root = tkinter.Tk()
            root.withdraw()
            try:
                root.clipboard_clear()
                root.clipboard_append(text)
                root.update()   # lets the system take a copy before the window goes away
            finally:
                root.destroy()
            return True
        except Exception:
            pass
    return False


def paste() -> str:
    """The clipboard's text, or "" if there is none (or it can't be read)."""
    if _termux_mode():
        ok, out = _termux(["termux-clipboard-get"])
        return out.replace("\x00", "").strip() if ok else ""
    try:
        import pygame
        pygame.scrap.init()
        data = pygame.scrap.get(pygame.SCRAP_TEXT)
        if data:
            if isinstance(data, bytes):
                data = data.decode("utf-8", "replace")
            return data.replace("\x00", "").strip()
    except Exception:
        pass
    if _use_tk():
        try:
            import tkinter
            root = tkinter.Tk()
            root.withdraw()
            try:
                return str(root.clipboard_get()).strip()
            finally:
                root.destroy()
        except Exception:
            pass
    return ""
