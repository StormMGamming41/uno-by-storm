#!/data/data/com.termux/files/usr/bin/bash
# Start the UNO game on Android.   Run:  bash run_android.sh        (or: bash run_android.sh check)
#   check   open the diagnostic (check_display.py) instead of the game
# UNTESTED on a real phone: written from Termux:X11 documentation.

cd "$(dirname "$0")" || exit 1
python -c "import pygame" 2>/dev/null || { echo "pygame is missing: run  bash termux_setup.sh  first."; exit 1; }

export DISPLAY="${DISPLAY:-:0}"
export SDL_VIDEODRIVER=x11
export SDL_AUDIODRIVER=dummy          # the game has no sound; keeps SDL from looking for audio
export SDL_VIDEO_WINDOW_POS=0,0       # no window manager: put the window in the corner
export PULSE_SERVER=                  # never wait for a sound server

XDIR="${TMPDIR:-$PREFIX/tmp}/.X11-unix"
LOG="${TMPDIR:-$PREFIX/tmp}/termux-x11.log"

# The socket of a running X server, if there is one (:0 -> X0). Echoes its display, e.g. ":0".
find_display() {
  for sock in "$XDIR/X${DISPLAY#:}" "$XDIR"/X*; do
    [ -S "$sock" ] && { echo ":${sock##*/X}"; return 0; }
  done
  return 1
}

if ! found=$(find_display); then
  echo "Starting the X server (termux-x11 $DISPLAY)..."
  command -v termux-x11 >/dev/null || { echo "termux-x11 is missing: run bash termux_setup.sh"; exit 1; }
  termux-x11 "$DISPLAY" >"$LOG" 2>&1 &
  for i in $(seq 1 30); do                       # up to 15 seconds: a first start can be slow
    found=$(find_display) && break
    sleep 0.5
  done
fi
if [ -z "${found:-}" ]; then
  echo
  echo "The X server did not start. What termux-x11 said:"
  sed 's/^/    /' "$LOG" 2>/dev/null | head -15
  echo "  X socket folder ($XDIR):"
  ls -la "$XDIR" 2>&1 | sed 's/^/    /'
  cat <<'HELP'

Things to try, in this order:
  1. Is it already running from an earlier try?   pkill -f termux-x11   then run this again.
  2. The Termux:X11 APP and the termux-x11-nightly PACKAGE must be the same version. If the app
     came from F-Droid (stable) but the package is the nightly one, install the nightly APK from
     the termux-x11 GitHub releases ("nightly") or the matching package.
  3. Start it by hand in a second Termux session and keep it open:   termux-x11 :0
     Then run this script again here; it will find the running server.
HELP
  exit 1
fi
export DISPLAY="$found"
echo "Using X display $DISPLAY"

# Bring the Termux:X11 app to the front so you can see the window (harmless if it fails).
am start --user 0 -n com.termux.x11/com.termux.x11.MainActivity >/dev/null 2>&1 || \
  echo "Open the Termux:X11 app yourself to see the game."
sleep 1

if [ "${1:-}" = "check" ]; then exec python check_display.py; fi
exec python main.py
