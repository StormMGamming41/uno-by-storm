import os, sys, tempfile, time
from harness import *
import settings; settings.SETTINGS_FILE = os.path.join(tempfile.mkdtemp(), "s.json")
import device; device.ANDROID = True; device.touch.enabled = True
W, H = (1080, 2400) if len(sys.argv) < 2 else tuple(int(v) for v in sys.argv[1].split("x"))
tag = sys.argv[2] if len(sys.argv) > 2 else "portrait"
pygame.display._desktop = (W, H)
import main, network
from viewport import view
g = main.Game(); run(g, 10)
print("canvas", view.size, "scale", view.scale, "picture", view.dest, "origin", view.origin)
for name in ("menu", "mode_select", "host", "join", "help"):
    g.change_scene(name); run(g, 8); shot(f"{tag}_{name}")
g.change_scene("join"); run(g, 8); tap(g, *canvas_to_window(view.size[0]//2, view.origin[1] + 200)); run(g, 12); shot(f"{tag}_join_kb")
g.disconnect(); g = main.Game(start_scene="host"); run(g, 5)
g.scene.online_box.checked = False; g.scene.port_box.text = "5595"; g.scene.start(); run(g, 5)
bot = network.Client(); bot.connect("127.0.0.1", 5595, name="Bot")
for _ in range(80): run(g, 1); bot.update(); time.sleep(0.02)
run(g, 5); shot(f"{tag}_lobby")
g.client.send({"type": "start"})
for _ in range(140): run(g, 1); bot.update(); time.sleep(0.01)
shot(f"{tag}_game"); g.disconnect()
