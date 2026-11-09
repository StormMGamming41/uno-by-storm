import os, tempfile, time
from harness import *
import settings; settings.SETTINGS_FILE = os.path.join(tempfile.mkdtemp(), "s.json")
import device; device.ANDROID = True; device.touch.enabled = True
pygame.display._desktop = (2400, 1080)
import main, network
from viewport import view
g = main.Game(); run(g, 12); shot("wide_menu")
g.change_scene("join"); run(g, 10)
tap(g, *canvas_to_window(view.size[0]//2, 200)); run(g, 12); shot("wide_join_keyboard")
g.disconnect(); g = main.Game(start_scene="host"); run(g, 5)
g.scene.online_box.checked = False; g.scene.port_box.text = "5596"; g.scene.start(); run(g, 5)
bot = network.Client(); bot.connect("127.0.0.1", 5596, name="Bot")
for _ in range(80): run(g, 1); bot.update(); time.sleep(0.02)
g.client.send({"type": "start"})
for _ in range(120): run(g, 1); bot.update(); time.sleep(0.01)
shot("wide_game"); print("canvas", view.size, "picture", view.dest)
g.disconnect()
