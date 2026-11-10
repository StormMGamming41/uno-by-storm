"""
Patches python-for-android's pygame recipe so a pygame APK builds AND starts.

    python ci/patch_pygame_recipe.py <path to a python-for-android checkout> [--cython "cython<3"]

Two fixes (each is skipped if already applied; the script fails loudly if the recipe looks different):

1. START-UP CRASH. Without it the app dies with "cannot locate symbol alphablit_alpha_sse2_argb_surf_alpha"
   and then "pg_has_avx2": the Android build of pygame's `surface` module leaves out two source files the
   code needs (src_c/simd_blitters_sse2.c and src_c/simd_blitters_avx2.c; the second just returns 0 on ARM).
   Confirmed on a real phone in kivy/python-for-android issue #3405. Not applied if the pygame version's
   build template already lists them.

2. "You need cython". pygame's build runs `hostpython setup.py build_ext`, where hostpython is python-for-
   android's OWN private Python, and that Python has no Cython. (Installing Cython on the build machine does
   not help: it is a different Python.) So Cython is put into hostpython's site-packages first, in two ways:
   - hostpython_prerequisites, python-for-android's own hook (only newer versions have it), and
   - a build_compiled_components override that pip-installs a Cython wheel there itself (works on any version).
"""
import re
import sys
from pathlib import Path

args = sys.argv[1:]
cython_spec = "cython<3"
if "--cython" in args:
    i = args.index("--cython")
    cython_spec = args[i + 1]
    del args[i:i + 2]
root = Path(args[0])
recipe = root / "pythonforandroid" / "recipes" / "pygame" / "__init__.py"
if not recipe.exists():
    sys.exit(f"pygame recipe not found: {recipe}")
text = recipe.read_text()
changed = []

# ---------------------------------------------------------------- 1. the start-up crash
if "simd_blitters_sse2.c" not in text:
    line = re.search(
        r'^([ \t]*)setup_template\s*=\s*open\(\s*join\(\s*["\']buildconfig["\']\s*,\s*'
        r'["\']Setup\.Android\.SDL2\.in["\']\s*\)\s*\)\.read\(\)[ \t]*$', text, re.M)
    if not line:
        sys.exit("the pygame recipe has changed: cannot find the line that reads Setup.Android.SDL2.in. "
                 "Nothing was patched. See kivy/python-for-android#3405.")
    ind = line.group(1)
    patch = (f'\n{ind}if "simd_blitters_sse2.c" not in setup_template:   # (this pygame version needs the fix)\n'
             f'{ind}    setup_template = setup_template.replace(\n'
             f'{ind}        "surface src_c/surface.c",\n'
             f'{ind}        "surface src_c/simd_blitters_sse2.c src_c/simd_blitters_avx2.c src_c/surface.c")')
    text = text[:line.end()] + patch + text[line.end():]
    changed.append("start-up crash fix")

# ---------------------------------------------------------------- 2. Cython for hostpython
if "UNO-PATCH cython" not in text:
    name_line = re.search(r'^([ \t]+)name\s*=\s*[\'"]pygame[\'"][ \t]*$', text, re.M)
    end_line = re.search(r'^recipe\s*=\s*\w+\(\)[ \t]*$', text, re.M)
    if not name_line or not end_line:
        sys.exit("the pygame recipe has changed: cannot place the Cython patch. Nothing was patched.")
    ind = name_line.group(1)
    attr = f"\n{ind}hostpython_prerequisites = ['setuptools', {cython_spec!r}]   # UNO-PATCH cython (newer p4a)"
    method = f'''
{ind}def build_compiled_components(self, arch):
{ind}    # UNO-PATCH cython: `hostpython setup.py build_ext` imports Cython, but hostpython (p4a's own private
{ind}    # Python) has none. Put a Cython wheel into ITS site-packages, using the build machine's pip.
{ind}    import glob
{ind}    import os
{ind}    import subprocess
{ind}    import sys
{ind}    root = os.path.dirname(os.path.dirname(self.hostpython_location))
{ind}    sites = glob.glob(os.path.join(root, "lib", "python3*", "site-packages"))
{ind}    if not sites:
{ind}        raise RuntimeError("UNO-PATCH cython: no site-packages under " + root)
{ind}    version = os.path.basename(os.path.dirname(sites[0]))[len("python"):]
{ind}    command = [sys.executable, "-m", "pip", "install", "--target", sites[0], "--upgrade",
{ind}               "--only-binary=:all:", "--no-deps", "--python-version", version, {cython_spec!r}]
{ind}    print("UNO-PATCH cython:", " ".join(command))
{ind}    subprocess.run(command, check=True)
{ind}    return super().build_compiled_components(arch)

'''
    text = text[:name_line.end()] + attr + text[name_line.end():]
    end_line = re.search(r'^recipe\s*=\s*\w+\(\)[ \t]*$', text, re.M)
    text = text[:end_line.start()].rstrip("\n") + "\n" + method + text[end_line.start():]
    changed.append(f"Cython ({cython_spec}) for hostpython")

if changed:
    recipe.write_text(text)
    print("pygame recipe patched:", ", ".join(changed))
else:
    print("pygame recipe already patched")
