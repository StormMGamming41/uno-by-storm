"""
Patches python-for-android's pygame recipe so the APK does not crash at startup.

Without it, the app dies with "cannot locate symbol alphablit_alpha_sse2_argb_surf_alpha" and
then "pg_has_avx2": the Android build of pygame's `surface` module leaves out two source files
the code needs (src_c/simd_blitters_sse2.c and src_c/simd_blitters_avx2.c; the second just
returns 0 on ARM). Found and confirmed on a real phone in kivy/python-for-android issue #3405.

    python ci/patch_pygame_recipe.py <path to a python-for-android checkout>

Safe to run twice. Exits non-zero (so the build stops with a clear message) if the recipe no
longer looks the way this patch expects.
"""
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
recipe = root / "pythonforandroid" / "recipes" / "pygame" / "__init__.py"
if not recipe.exists():
    sys.exit(f"pygame recipe not found: {recipe}")

text = recipe.read_text()
MARK = "simd_blitters_sse2.c"
if MARK in text:
    print("pygame recipe already patched")
    sys.exit(0)

line = re.search(r'^([ \t]*)setup_template\s*=\s*open\(join\("buildconfig",\s*"Setup\.Android\.SDL2\.in"\)\)\.read\(\)[ \t]*$',
                 text, re.M)
if not line:
    sys.exit("the pygame recipe has changed: cannot find the line that reads Setup.Android.SDL2.in. "
             "Nothing was patched. See issue kivy/python-for-android#3405.")

indent = line.group(1)
patch = (f'\n{indent}setup_template = setup_template.replace(\n'
         f'{indent}    "surface src_c/surface.c",\n'
         f'{indent}    "surface src_c/simd_blitters_sse2.c src_c/simd_blitters_avx2.c src_c/surface.c")')
recipe.write_text(text[:line.end()] + patch + text[line.end():])
print("pygame recipe patched:", recipe)
