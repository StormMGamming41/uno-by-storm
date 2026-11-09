"""
What kind of device are we on, and is touch mode on?

Touch mode = an on-screen keyboard drawn by the game, and tap-to-raise / tap-again-to-play
for cards. It is switched on automatically on Android (Termux) and can be toggled anywhere
with the F3 key or the button on the main menu. The player's choice is remembered.
"""

import os
import sys

import settings


def is_android() -> bool:
    """True when running inside Termux / on Android."""
    return (sys.platform == "android"                      # Python 3.13+ on Android
            or "TERMUX_VERSION" in os.environ              # set by recent Termux versions
            or "com.termux" in os.environ.get("PREFIX", "")  # Termux's install prefix
            or "ANDROID_ROOT" in os.environ and "ANDROID_DATA" in os.environ)


def is_termux() -> bool:
    """True only inside Termux (a development setup). A packaged APK is Android but not Termux."""
    return (os.environ.get("TERMUX_VERSION") is not None
            or "com.termux" in os.environ.get("PREFIX", ""))


ANDROID = is_android()
IN_TERMUX = is_termux()


class Touch:
    def __init__(self):
        self.enabled = ANDROID

    def load(self):
        """A saved choice wins; otherwise touch mode is on exactly when we're on Android."""
        saved = settings.get("touch")
        self.enabled = saved if isinstance(saved, bool) else ANDROID

    def set(self, value: bool, save: bool = True):
        self.enabled = bool(value)
        if save:
            settings.save(touch=self.enabled)   # only the "touch" key; theme is kept

    def toggle(self):
        self.set(not self.enabled)


touch = Touch()
