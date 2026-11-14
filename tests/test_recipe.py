"""
The pygame-ce recipe, run against a STAND-IN for python-for-android's recipe classes (the real
python-for-android is not installed here). Checks what the recipe decides, not that Android builds.
"""
import importlib.util, os, subprocess, sys, tempfile, types
HERE = os.path.dirname(os.path.abspath(__file__))
ok = fail = 0
def check(name, cond, extra=""):
    global ok, fail
    if cond: ok += 1; print("PASS", name)
    else: fail += 1; print("FAIL", name, extra)

# ---- a stand-in python-for-android
tmp = tempfile.mkdtemp()
build_dir = os.path.join(tmp, "build"); os.makedirs(os.path.join(build_dir, "buildconfig")); os.makedirs(os.path.join(build_dir, "src_c"))
calls = []
class Base:
    def prebuild_arch(self, arch): calls.append("base.prebuild_arch")
    def get_build_dir(self, arch): return build_dir
    def get_recipe(self, name, ctx):
        r = types.SimpleNamespace()
        r.get_build_dir = lambda a: os.path.join(tmp, name, str(a))
        r.get_include_dirs = lambda a: ["/inc/mixer1", "/inc/mixer2"]
        return r
    def get_recipe_env(self, arch): return {"BASE": "1"}
    def build_compiled_components(self, arch): calls.append("base.build_compiled_components")
pkg = types.ModuleType("pythonforandroid"); sys.modules["pythonforandroid"] = pkg
rec = types.ModuleType("pythonforandroid.recipe"); rec.CompiledComponentsPythonRecipe = Base; sys.modules["pythonforandroid.recipe"] = rec
import contextlib
tc = types.ModuleType("pythonforandroid.toolchain")
@contextlib.contextmanager
def cd(path):
    old = os.getcwd(); os.chdir(path)
    try: yield
    finally: os.chdir(old)
tc.current_directory = cd; sys.modules["pythonforandroid.toolchain"] = tc
lg = types.ModuleType("pythonforandroid.logger"); logs = []
lg.info = lambda m: logs.append(("info", m)); lg.warning = lambda m: logs.append(("warning", m)); sys.modules["pythonforandroid.logger"] = lg

spec = importlib.util.spec_from_file_location("pgce", os.path.join(HERE, "..", "recipes", "pygame-ce", "__init__.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
R = mod.recipe
class Arch:
    arch = "arm64-v8a"; ndk_lib_dir_versioned = "/ndk/lib21"; ndk_lib_dir = "/ndk/lib"
    def __str__(self): return self.arch
arch = Arch()
R.ctx = types.SimpleNamespace(bootstrap=types.SimpleNamespace(build_dir="/boot"))

check("recipe identity", R.name == "pygame-ce" and R.version == "2.4.1" and "pygame-ce" in R.url)
check("depends on the SDL pieces + png/jpeg", {"sdl2", "sdl2_image", "sdl2_mixer", "sdl2_ttf", "png", "jpeg", "setuptools"} <= set(R.depends))
check("no leftover use of ctx.ndk.sysroot", "ndk.sysroot" not in open(os.path.join(HERE, "..", "recipes", "pygame-ce", "__init__.py")).read().replace("`ctx.ndk.sysroot`", "").split('"""', 2)[-1])

def write_template(text, simd_files=True):
    open(os.path.join(build_dir, "buildconfig", "Setup.Android.SDL2.in"), "w").write(text)
    for f in mod.SIMD_FILES:
        p = os.path.join(build_dir, f)
        if simd_files: open(p, "w").write("x")
        elif os.path.exists(p): os.remove(p)

TEMPLATE = "SDL = {sdl_includes}\nTTF = {sdl_ttf_includes}\nIMG = {sdl_image_includes}\nMIX = {sdl_mixer_includes}\nJPG = {jpeg_includes}\nPNG = {png_includes}\nFT = {freetype_includes}\nFUTURE = {future_placeholder}\nsurface src_c/surface.c\n"
write_template(TEMPLATE, simd_files=True)
R.prebuild_arch(arch)
setup = open(os.path.join(build_dir, "Setup")).read()
check("Setup file written with the includes", "-I/boot/jni/SDL/include" in setup and "-L/boot/libs/arm64-v8a" in setup and "-L/ndk/lib21" in setup and "-I/inc/mixer1 -I/inc/mixer2" in setup, setup[:200])
check("unknown placeholder tolerated (empty), not a KeyError", "FUTURE = \n" in setup)
check("SIMD sources added when needed and present", "surface src_c/simd_blitters_sse2.c src_c/simd_blitters_avx2.c src_c/surface.c" in setup, setup[-120:])

write_template(TEMPLATE.replace("surface src_c/surface.c", "surface src_c/simd_blitters_sse2.c src_c/simd_blitters_avx2.c src_c/surface.c"), simd_files=True)
R.prebuild_arch(arch); setup = open(os.path.join(build_dir, "Setup")).read()
check("SIMD sources NOT duplicated when already listed", setup.count("simd_blitters_sse2.c") == 1, setup.count("simd_blitters_sse2.c"))
write_template(TEMPLATE, simd_files=False)
R.prebuild_arch(arch); setup = open(os.path.join(build_dir, "Setup")).read()
check("SIMD sources not added when this version has no such files", "simd_blitters" not in setup)
write_template(TEMPLATE.replace("surface src_c/surface.c", "something else"), simd_files=True)
logs.clear(); R.prebuild_arch(arch); setup = open(os.path.join(build_dir, "Setup")).read()
check("unknown surface line: left alone and a warning logged", "simd_blitters" not in setup and any(k == "warning" for k, _ in logs), logs)

# ---- Cython for hostpython
host = os.path.join(tmp, "root", "usr", "local"); os.makedirs(os.path.join(host, "bin")); os.makedirs(os.path.join(host, "lib", "python3.11", "site-packages"))
R.hostpython_location = os.path.join(host, "bin", "python")
real_run = subprocess.run; seen = []
def make_run(has_cython, pip_fails=False):
    def fake(cmd, **kw):
        seen.append(cmd)
        if cmd[-2:] == ["-c", "import Cython"]: return types.SimpleNamespace(returncode=0 if has_cython else 1)
        if pip_fails: raise subprocess.CalledProcessError(1, cmd)
        return types.SimpleNamespace(returncode=0)
    return fake
for label, has, fails in (("hostpython already has Cython", True, False), ("hostpython lacks Cython", False, False), ("pip fails", False, True)):
    seen.clear(); calls.clear(); subprocess.run = make_run(has, fails)
    try:
        R.build_compiled_components(arch); err = None
    except Exception as e:
        err = repr(e)
    subprocess.run = real_run
    pips = [c for c in seen if "pip" in c]
    if label == "hostpython already has Cython":
        check(f"{label}: no pip run", not pips and calls == ["base.build_compiled_components"], (pips, calls))
    elif label == "hostpython lacks Cython":
        cmd = pips[0] if pips else []
        check(f"{label}: pip installs a wheel into hostpython's python3.11 site-packages", "--target" in cmd and cmd[cmd.index("--target") + 1].endswith("python3.11/site-packages") and "3.11" in cmd and "cython<3" in cmd and "--only-binary=:all:" in cmd, cmd)
        check(f"{label}: then the real build runs", calls == ["base.build_compiled_components"], calls)
    else:
        check(f"{label}: build is NOT stopped, and it still runs", err is None and calls == ["base.build_compiled_components"], (err, calls))
check("environment flags set", R.get_recipe_env(arch) == {"BASE": "1", "USE_SDL2": "1", "PYGAME_CROSS_COMPILE": "TRUE", "PYGAME_ANDROID": "TRUE"})
print(f"\n{ok} passed, {fail} failed")
