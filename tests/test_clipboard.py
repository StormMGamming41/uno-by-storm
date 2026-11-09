import os, stat, tempfile, time
FAKE = tempfile.mkdtemp()
CLIP = os.path.join(FAKE, "clip.txt")
for name, body in (("termux-clipboard-get", "#!/bin/sh\nsleep 30\n"),
                   ("termux-clipboard-set", "#!/bin/sh\ncat > %s\n" % CLIP)):
    path = os.path.join(FAKE, name)
    open(path, "w").write(body)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
OLD_PATH = os.environ["PATH"]
os.environ["PATH"] = FAKE + os.pathsep + OLD_PATH
from harness import *
import device; device.ANDROID = True; device.IN_TERMUX = True
import clipboard
clipboard.TERMUX_TIMEOUT = 1.0
assert clipboard.copy("ROOM-1234") and open(CLIP).read() == "ROOM-1234"; print("PASS copy works")
t = time.time(); r = clipboard.paste(); d = time.time() - t
assert r == "" and 0.9 < d < 2.5 and clipboard.unavailable_reason, (r, d); print(f"PASS hung paste gave up after {d:.1f}s:", clipboard.unavailable_reason)
t = time.time(); clipboard.paste(); clipboard.copy("x"); d = time.time() - t
assert d < 0.2; print(f"PASS later calls return instantly ({d*1000:.0f} ms), no more freezing")
clipboard.unavailable_reason = ""; os.environ["PATH"] = "/nonexistent"
assert clipboard.paste() == "" and "not installed" in clipboard.unavailable_reason; print("PASS missing command:", clipboard.unavailable_reason)
