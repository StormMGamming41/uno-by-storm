"""
One small settings file (settings.json, next to the game files) shared by everything that
wants to remember something: the light/dark theme, touch mode, ...

Each setting is saved by changing ONLY its own key. The file is re-read right before every
write, so saving the theme can never erase the touch setting (or the other way round), and
keys this version doesn't know about are kept as they are.
"""

import json
import os
import sys


def _settings_dir() -> str:
    """Where settings.json lives. Next to the game files while developing, but a packaged game
    can't write there: an Android app has a private folder, and a Windows one-file exe runs from
    a temporary folder that is deleted on exit."""
    private = os.environ.get("ANDROID_PRIVATE")             # set by python-for-android APKs
    if private and os.path.isdir(private):
        return private
    if getattr(sys, "frozen", False):                      # PyInstaller exe
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        folder = os.path.join(base, "UnoByStorm")
        try:
            os.makedirs(folder, exist_ok=True)
            return folder
        except OSError:
            pass
    return os.path.dirname(os.path.abspath(__file__))


SETTINGS_FILE = os.path.join(_settings_dir(), "settings.json")


def load() -> dict:
    """Everything saved so far. {} if there is no file yet or it can't be read."""
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def get(key, default=None):
    return load().get(key, default)


def save(**changes) -> bool:
    """Merge `changes` into the saved settings. Returns False if the file can't be written."""
    data = load()
    data.update(changes)
    tmp = SETTINGS_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, SETTINGS_FILE)   # all-or-nothing, so a crash can't leave half a file
        return True
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False   # read-only folder: settings just won't be remembered
