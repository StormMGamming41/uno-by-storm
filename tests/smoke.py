import os, tempfile
from harness import *
import settings
settings.SETTINGS_FILE = os.path.join(tempfile.mkdtemp(), "settings.json")
import device
device.ANDROID = True; device.touch.enabled = True
import main
g = main.Game()
run(g, 12)
shot("menu_android")
print("window", pygame.display._window.get_size(), "dest", __import__("viewport").view.dest, "scale", __import__("viewport").view.scale)
