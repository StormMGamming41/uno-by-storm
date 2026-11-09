#!/usr/bin/env bash
# Runs inside the Android emulator job. Installs the APK, then launches it several times, alternating
# between starting UPRIGHT and starting SIDEWAYS (the case that crashed on real phones), and checks
# each launch: still running after the wait, no crash in the log, something drawn, right orientation.
# Saves a screenshot and the log of every launch. NOT RUN by me (it needs an emulator).
set -u
PKG=org.storm.unobystorm
APK=$(find bin -maxdepth 1 -type f -name '*.apk' -print -quit 2>/dev/null)
OUT=ci_out; mkdir -p "$OUT"
[ -n "$APK" ] || {
  echo "No APK found in bin/. Contents of bin/:"
  ls -lah bin/ 2>&1 || true
  echo "APK files anywhere in the workspace:"
  find . -type f -name '*.apk' -print 2>/dev/null || true
  exit 1
}

adb wait-for-device
adb shell input keyevent 82 >/dev/null 2>&1                 # wake / unlock
adb shell settings put system accelerometer_rotation 0       # we choose the orientation, not the sensor
echo "Installing $APK"
adb install -r "$APK" || { echo "INSTALL FAILED"; exit 1; }

STATUS=0
N=0
# rotation: 0 = upright, 1 = sideways
for ROT in 0 1 1 0 1; do
  N=$((N + 1))
  LABEL=$([ "$ROT" = 0 ] && echo upright || echo sideways)
  echo "=== launch $N: starting $LABEL ==="
  adb shell am force-stop "$PKG"
  adb shell settings put system user_rotation "$ROT"
  sleep 4                                                    # let the emulator finish rotating
  adb logcat -c
  adb shell monkey -p "$PKG" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1
  [ "$N" = 1 ] && sleep 70 || sleep 35                       # the first start unpacks Python: slower
  PNG="$OUT/launch${N}_${LABEL}.png"; LOG="$OUT/launch${N}_${LABEL}.logcat.txt"
  adb exec-out screencap -p > "$PNG"
  adb logcat -d > "$LOG"
  PID=$(adb shell pidof "$PKG" | tr -d '\r')
  if [ -z "$PID" ]; then
    echo "FAIL launch $N ($LABEL): the app is not running (crashed or never started). Relevant log:"
    grep -iE "python|unobystorm|FATAL|ImportError|dlopen|cannot locate|SDL|signal 11|SIGSEGV" "$LOG" | tail -50
    STATUS=1; continue
  fi
  if grep -qE "SIGSEGV|signal 11|Fatal signal|cannot locate symbol|ImportError|Traceback \(most recent call last\)" "$LOG"; then
    echo "FAIL launch $N ($LABEL): errors in the log:"
    grep -E -B2 -A10 "SIGSEGV|signal 11|Fatal signal|cannot locate symbol|ImportError|Traceback \(most recent call last\)" "$LOG" | head -50
    STATUS=1
  fi
  python3 - "$PNG" "$LABEL" <<'PY' || STATUS=1
import sys
from PIL import Image
im = Image.open(sys.argv[1]).convert("RGB"); w, h = im.size
small = im.resize((max(1, w // 10), max(1, h // 10)))
px = list(small.getdata()); lit = sum(1 for r, g, b in px if r + g + b > 60) / len(px)
want_wide = sys.argv[2] == "sideways"
print(f"  screenshot {w}x{h}, {lit:.0%} not black")
ok = True
if lit < 0.10:
    print("  FAIL: (almost) black screen - the game did not draw"); ok = False
if (w > h) != want_wide:
    print(f"  FAIL: wanted a {sys.argv[2]} screen but the screenshot is {w}x{h}"); ok = False
print("  PASS" if ok else "  (see above)")
sys.exit(0 if ok else 1)
PY
done

# the game's own record of what its display did (written by the app, readable only with run-as on debug builds)
adb shell "run-as $PKG cat files/app/display.log" > "$OUT/display.log" 2>/dev/null || true
adb shell "run-as $PKG cat files/app/crash.log" > "$OUT/crash.log" 2>/dev/null || true
echo "exit status $STATUS"
exit $STATUS
