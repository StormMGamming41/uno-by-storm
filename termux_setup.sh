#!/data/data/com.termux/files/usr/bin/bash
# One-time setup of the UNO game inside Termux.   Run:  bash termux_setup.sh
#   --check   only report what is installed, download nothing
#   --yes     don't ask before downloading
# UNTESTED on a real phone: written from Termux documentation. If a step fails, the
# message says which one; README_ANDROID.md lists the manual commands.

set -u
say()  { printf '\n== %s\n' "$*"; }
fail() { printf '\nFAILED: %s\n' "$*" >&2; exit 1; }

case "${PREFIX:-}" in *com.termux*) ;; *) fail "this script is for Termux on Android.";; esac
CHECK=0; YES=0
for a in "$@"; do [ "$a" = "--check" ] && CHECK=1; [ "$a" = "--yes" ] && YES=1; done

have() { command -v "$1" >/dev/null 2>&1; }
say "What is installed now"
for c in python clang make pkg-config termux-x11 termux-clipboard-get; do
  if have "$c"; then echo "  ok       $c"; else echo "  missing  $c"; fi
done
if python -c "import pygame" 2>/dev/null; then echo "  ok       pygame $(python -c 'import pygame;print(pygame.version.ver)' 2>/dev/null | tail -1)"; else echo "  missing  pygame"; fi
[ "$CHECK" = 1 ] && exit 0

say "This downloads the compiler, SDL2 and the X11 server app packages, then builds pygame"
echo "  (several hundred MB in total and several minutes). Use Wi-Fi, not mobile data."
if [ "$YES" = 0 ]; then read -r -p "  Press Enter to continue, Ctrl+C to cancel: " _; fi

say "1/4  X11 repository"
pkg install -y x11-repo || fail "could not add x11-repo (no internet?)"

say "2/4  Packages"
pkg install -y termux-x11-nightly python clang make pkg-config \
    sdl2 sdl2-image sdl2-mixer sdl2-ttf xorgproto termux-api \
  || fail "pkg install failed. Try 'pkg update' and run this script again."

say "3/4  pygame (builds from source: takes minutes, the phone may get warm)"
if python -c "import pygame" 2>/dev/null; then
  echo "  already installed"
else
  pip install pygame || fail "pygame did not build. Run:  pip install pygame -v  and send me the last 30 lines."
fi

say "4/4  Check"
python -c "import pygame; print('pygame', pygame.version.ver)" || fail "pygame is not importable"
cat <<'MSG'

Done. Still to do by hand (Android apps, not installable from here):
  * Termux:X11 app   - the window the game appears in
  * Termux:API app   - only needed for the Paste key (same source as Termux: F-Droid or GitHub)
Then:  bash run_android.sh        (details: README_ANDROID.md)
MSG
