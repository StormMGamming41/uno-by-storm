# Android APK build with Buildozer / python-for-android. Built by the GitHub workflow in
# .github/workflows/build.yml (nothing to install on your own computer). NOT built by me.
# Packaging pygame for Android is fragile; the workflow patches python-for-android's pygame
# recipe (see ci/patch_pygame_recipe.py) and tries two pygame versions side by side.

[app]
title = UNO By Storm
package.name = unobystorm
package.domain = org.storm
source.dir = .
source.include_exts = py,png,ttf,json,md
source.exclude_dirs = tests,bin,.buildozer,.github,ci,p4a
version = 1.0

# only pygame(-ce) + the standard library. The workflow sets this line from the recipe in recipes/.
requirements = python3,pygame-ce

# our own loading screen and icon (the default is a Kivy one)
presplash.filename = %(source.dir)s/data/presplash.png
icon.filename = %(source.dir)s/data/icon.png
android.presplash_color = #2e7d57

# the game picks its layout from the real screen shape, so let the phone rotate freely
orientation = all
fullscreen = 1

# direct TCP games and the built-in online rooms need the network
android.permissions = INTERNET,ACCESS_NETWORK_STATE
# arm64 = nearly every phone; x86_64 = the emulator the workflow tests on
android.archs = arm64-v8a, x86_64
android.minapi = 21
android.accept_sdk_license = True

# the workflow replaces these lines: the patched python-for-android checkout, and (for the older
# python-for-android releases) the NDK version they were made for
# p4a.source_dir =
# android.ndk =
# p4a.local_recipes =

[buildozer]
log_level = 2
warn_on_root = 1
