# UNO on Android (Termux) with a GUI

**Status: nothing here has been run on a real phone yet.** The game logic, scaling, tap mapping,
on-screen keyboard, tap-to-raise cards, clipboard timeout and settings were tested with a PIL
stand-in for pygame (`tests/`). The Termux steps, `termux_setup.sh`, `run_android.sh`, and how
Termux:X11 delivers taps are written from documentation and are **untested**.
Run the diagnostic (step 5) first and send me its report if anything is off.

## 1. Install the apps (not from the Play Store)
Get these from **F-Droid** or the projects' **GitHub releases** (all from the same source):
1. **Termux**
2. **Termux:X11** (the window the game shows up in)
3. **Termux:API** (only for the Paste key; the game works without it)

## 2. Copy the game to the phone
Easiest on a small data budget: copy `uno_android.zip` over USB or Bluetooth, no internet needed.
In Termux:
```
termux-setup-storage          # allow file access (once)
cd ~ && unzip /sdcard/Download/uno_android.zip -d uno && cd uno
```
If a `.sh` file complains about `\r`, Windows changed its line endings: `sed -i 's/\r$//' *.sh`

## 3. One-time setup (this is the part that uses data)
```
bash termux_setup.sh          # asks first; --check shows what's installed without downloading
```
It installs the compiler, SDL2 and X11 packages and **builds pygame from source**
(several hundred MB of downloads, estimated, not measured; takes minutes). Use Wi-Fi. The game
itself uses almost no data; the Windows updates were never its fault.

## 4. In the Termux:X11 app (once)
Preferences, then:
- **Input > Touch mode: Simulated touchscreen** (taps become clicks)
- **Display resolution mode: custom, 1280x720** (faster than your phone's native size)

## 5. Check, then play
```
bash run_android.sh check     # taps 5 circles, types uno:/1, prints a report
bash run_android.sh           # the game
```
`check_display_report.txt` is saved; paste it to me if anything is reported as a problem.

## Screen sizes and layout (replaces the old "scale everything" idea)
There is no continuous resizing. The game is laid out for a few fixed canvas shapes and positions things from the canvas size:
- **Phone held upright:** 540 wide, as tall as the screen's shape needs (a 1080x2400 screen is exactly 2x: sharp and cheap to draw).
- **Phone held sideways:** 600 tall, as wide as needed (about 1333 on a 20:9 screen).
- **PC:** 800x600 canvas in a **fixed-size window** (not draggable). **F4** switches between the fixed sizes that fit your desktop (800x600, 1200x900, 1600x1200).
- Rotating the phone rebuilds the screen for the new shape (typed text on that screen is lost).
- On Android the real screen size is read back after the window exists, then the shape is chosen from it. `check_display.py` prints it (`screen:` and `window` lines): if something still looks wrong, send me those two lines.
- Camera notch hiding the edges? `UNO_MARGIN=4 bash run_android.sh`. Want the old 4:3 picture? `UNO_FILL=0`.

## Building and testing the EXE and the APK in the cloud (nothing to install on your PC)
Termux is only for quick tests. The game itself needs only pygame and the standard library, so it can be packaged.

**One-time setup (browser only, a free GitHub account is enough):**
1. github.com > New repository (private is fine) > create it.
2. "uploading an existing file" > unzip `uno_android.zip` on your PC and drag **everything inside the `uno` folder** in, including the hidden `.github` folder (Windows: turn on View > Hidden items first) > Commit.
3. Open the **Actions** tab. The `build` workflow starts by itself (or press "Run workflow"). Downloading the results later is the only real data use (the EXE and APK are tens of MB each; the build itself runs on GitHub's servers).

**What it does, and where to look:**
| Job | What it proves | Download from the run page |
|---|---|---|
| tests | the game's test suite passes | (log only) |
| windows | builds `UnoByStorm.exe` **and runs it** with `--selftest`: fonts, settings, every screen, a real 2-player game over localhost | `windows-exe` (exe + `selftest_result.txt`) |
| android (4 variants) | builds the APK with the pygame start-up crash patched (see `ci/patch_pygame_recipe.py`), then **launches it 5 times in an Android emulator, alternating upright and sideways starts**, screenshotting each | `apk-...`, `build-log-...`, `emulator-...` (screenshots, logcat) |

If a job fails, download its `build-log-...` / `emulator-...` artifact and send me the last part: it names the exact line that broke. The Android job is the fragile one (pygame on Android is not an officially supported combination), which is why it builds the game four ways side by side (three python-for-android versions with the recipe's own pygame 2.1.0, plus the newest python-for-android with pygame 2.6.1): if one variant passes, install that variant's APK. **The first cloud run failed on `You need cython`**: pygame's build runs with python-for-android's own private Python, which has no Cython, and installing Cython on the build machine does not reach it. `ci/patch_pygame_recipe.py` now installs a Cython wheel into that private Python before pygame builds (tested against a stand-in for the recipe, not on the real thing). **When a variant fails, the run page shows a "Why the build failed" summary**: the first error-looking lines of the log with their surroundings, so you can read or send me the cause directly instead of searching the full log.

**Testing the APK on your own phone:** download `apk-...` > unzip > install the `.apk` (allow "install unknown apps" for your browser/file manager). Menu > **Screen info** shows what the display reports, plus the game's own log of what the display did (sizes, rotations, errors). A crash is also saved to `crash.log` in the app's private folder and shown on screen. For a real log: enable USB debugging and run `adb logcat -s python:*` (needs a computer with adb).

**Windows exe on your own PC (optional):** `build_windows.bat`. Run `UnoByStorm.exe --selftest` to check it the same way the cloud does.

## Rotation and start-up (what was found on real phones, and what changed)
The first APK built from this project showed two problems: a messy upright layout, and landscape launches that crashed (unless the phone was rotated during start-up). Reading the code with those symptoms, these were real weaknesses, now fixed, with tests that fail when the old behaviour is put back:
- the screen size was read before Android had finished rotating, and from two different SDL calls that can disagree. Now the game waits until the size reads the same several times, checks that the window and the display agree about upright/sideways (recreating the window once if not), and uses the real surface size everywhere;
- the window surface was kept between frames, but SDL can replace it at any moment (rotation, app switch), and drawing into a replaced one is an error. Now it is fetched fresh every time, and a changed one is noticed at the start of the next frame, before anything is drawn;
- the canvas shape was changed in the middle of a frame while the old canvas was still in use. Now the shape and the canvas change together, before drawing;
- sideways phones took the riskiest drawing path (smooth scaling straight into a piece of the window's own surface) while upright ones took a simpler one, which would explain "portrait mostly works, landscape crashes". Scaling now only touches the game's own 32-bit surfaces and the window only receives a plain copy;
- a display error during drawing no longer ends the game: it is counted and the game looks at the window again. **The real crash cause is still unconfirmed**: I have no logcat. These are fixes for bugs I could demonstrate, not proof that they are your crash. The emulator test (launching sideways repeatedly) and `display.log` are there to show whether it is gone.

## How touch mode works
- It is **on automatically** on Android. Elsewhere: **F3**, or the *Touch mode* button on the main menu. The choice is remembered.
- **Typing:** tap a text box and the game's own keyboard slides up and lifts the screen so the box stays visible. Keys: numbers, Shift (double-tap = caps lock), `?123` page (has `:` and `/`), Paste, Hide, Go, Del (hold to repeat). Keys the box won't accept are greyed.
- **Cards:** tap a card to raise it (so you can see it among overlapping cards), tap it again to play it. Tap anywhere else to put it back.
- **Paste** uses Termux:API. If the app is missing, the first press waits up to 4 seconds, then Paste is switched off for the session and says why. Nothing freezes after that.

## Known limits / things I can't promise
- Android's own keyboard is not used on purpose (it doesn't reliably send keys over X11).
- Android 12+ may kill Termux in the background (the "phantom process killer"). Keep the game in front.
- **Speed at your phone's native resolution:** a native screen means scaling and sending millions of pixels per frame, which is what made it slow. The game now sends nothing when the picture hasn't changed, and only the changed strips when part of it has, then repaints in full once after things go quiet. Waiting, typing and tapping are cheap. Bursts where the whole screen changes (a new screen fading in, the deal at the start of a round) are still full frames, so a brief stutter there is expected. If smooth scaling is slow it switches to fast scaling by itself (`UNO_SCALE=fast` forces that; `UNO_SCALE=smooth` never switches). Lowering the Termux:X11 resolution is still the biggest single speed-up.
- Windows: the window is now a fixed size (F4 changes it); F3 toggles touch mode.

## Manual commands (if the script fails)
```
pkg install x11-repo
pkg install termux-x11-nightly python clang make pkg-config sdl2 sdl2-image sdl2-mixer sdl2-ttf xorgproto termux-api
pip install pygame
termux-x11 :0 &  export DISPLAY=:0  &&  python main.py
```
