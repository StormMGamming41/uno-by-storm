"""
python-for-android recipe: pygame-ce (the community edition of pygame, SDL2) for an Android APK.

Based on two public recipes that are known to compile, and credit goes to their authors:
  * emersonmx, "Setup a game with Pygame CE for Android" (gist c5bba202506e3c3d2d828ad278a8d5fe)
  * cbdj, Potato-Bird, recipes/pygame-ce/__init__.py (a game published on Google Play)
which in turn derive from python-for-android's own (MIT licensed) pygame recipe.

Why 2.4.1: a user of the gist recipe reports that pygame-ce 2.5.0 needs Cython added by hand, while the
Potato-Bird recipe (2.4.1) builds without it.

What is different from those recipes (each point is a way they can break on another python-for-android):
  * the unused `env['ANDROID_ROOT'] = join(self.ctx.ndk.sysroot, ...)` lines are gone (the variable was never
    used, but `ctx.ndk.sysroot` may not exist in a newer python-for-android);
  * the Setup template is filled in with a formatter that tolerates placeholders it doesn't know, so another
    pygame-ce version's template doesn't die with a KeyError;
  * if this pygame-ce version's template leaves out the SIMD blitter sources that surface.c needs (the cause
    of the start-up crash "cannot locate symbol alphablit_alpha_sse2_argb_surf_alpha", kivy/python-for-android
    issue #3405), they are added, but only if the files exist and are not already listed;
  * if python-for-android's private build Python (hostpython3) has no Cython, a Cython wheel is put there, as
    a best effort that never stops the build ("You need cython" is what broke an earlier build).
NOT BUILT OR TESTED against the real python-for-android by me.
"""
import glob
import os
import string
import subprocess
import sys
from os.path import exists, join

from pythonforandroid.recipe import CompiledComponentsPythonRecipe
from pythonforandroid.toolchain import current_directory

try:
    from pythonforandroid.logger import info, warning
except ImportError:                      # very old python-for-android
    info = warning = print

CYTHON_SPEC = "cython<3"                 # pygame-ce 2.4.1 predates Cython 3
SIMD_FILES = ("src_c/simd_blitters_sse2.c", "src_c/simd_blitters_avx2.c")


class _TolerantFormatter(string.Formatter):
    """Like str.format, but a placeholder that was not given is replaced by nothing."""

    def get_value(self, key, args, kwargs):
        if isinstance(key, str):
            return kwargs.get(key, "")
        return super().get_value(key, args, kwargs)


class PygameCERecipe(CompiledComponentsPythonRecipe):
    """
    Recipe to build apps based on SDL2-based pygame-ce.

    .. warning:: freetype, portmidi and (here) libjpeg are not part of the build. pygame.font (SDL_ttf),
       pygame.image (SDL_image) and pygame.mixer (SDL_mixer) are.
    """

    version = "2.4.1"
    url = "https://github.com/pygame-community/pygame-ce/archive/{version}.tar.gz"

    site_packages_name = "pygame-ce"
    name = "pygame-ce"

    depends = ["sdl2", "sdl2_image", "sdl2_mixer", "sdl2_ttf", "setuptools", "jpeg", "png"]
    call_hostpython_via_targetpython = False       # because of setuptools
    install_in_hostpython = False

    # ------------------------------------------------------------------ the Setup file

    def prebuild_arch(self, arch):
        super().prebuild_arch(arch)
        with current_directory(self.get_build_dir(arch.arch)):
            setup_template = open(join("buildconfig", "Setup.Android.SDL2.in")).read()

            png = self.get_recipe("png", self.ctx)
            png_lib_dir = join(png.get_build_dir(arch.arch), ".libs")
            png_inc_dir = png.get_build_dir(arch.arch)

            jpeg = self.get_recipe("jpeg", self.ctx)
            jpeg_inc_dir = jpeg_lib_dir = jpeg.get_build_dir(arch.arch)

            sdl_mixer_includes = ""
            sdl2_mixer_recipe = self.get_recipe("sdl2_mixer", self.ctx)
            for include_dir in sdl2_mixer_recipe.get_include_dirs(arch):
                sdl_mixer_includes += f"-I{include_dir} "

            ndk_lib_dir = getattr(arch, "ndk_lib_dir_versioned", None) or arch.ndk_lib_dir
            bootstrap = self.ctx.bootstrap.build_dir

            setup_file = _TolerantFormatter().format(
                setup_template,
                sdl_includes=(" -I" + join(bootstrap, "jni", "SDL", "include")
                              + " -L" + join(bootstrap, "libs", str(arch))
                              + " -L" + png_lib_dir
                              + " -L" + jpeg_lib_dir
                              + " -L" + ndk_lib_dir),
                sdl_ttf_includes="-I" + join(bootstrap, "jni", "SDL2_ttf"),
                sdl_image_includes="-I" + join(bootstrap, "jni", "SDL2_image", "include"),
                sdl_mixer_includes=sdl_mixer_includes,
                jpeg_includes="-I" + jpeg_inc_dir,
                png_includes="-I" + png_inc_dir,
                freetype_includes="",
            )
            setup_file = self._with_simd_sources(setup_file)
            open("Setup", "w").write(setup_file)

    @staticmethod
    def _with_simd_sources(setup_file):
        """Add the SIMD blitter sources to the `surface` module if surface.c needs them (see above)."""
        if "simd_blitters_sse2.c" in setup_file:
            return setup_file                                   # already listed
        if not all(exists(f) for f in SIMD_FILES):
            return setup_file                                   # this version has no such files
        marker = "surface src_c/surface.c"
        if marker not in setup_file:
            warning("pygame-ce recipe: could not find the surface module line; SIMD sources not added")
            return setup_file
        info("pygame-ce recipe: adding the SIMD blitter sources to the surface module")
        return setup_file.replace(marker, "surface " + " ".join(SIMD_FILES) + " src_c/surface.c", 1)

    # ------------------------------------------------------------------ Cython for hostpython

    def build_compiled_components(self, arch):
        self._ensure_hostpython_cython()
        return super().build_compiled_components(arch)

    def _ensure_hostpython_cython(self):
        """pygame-ce's build runs `hostpython setup.py build_ext`, which imports Cython if it has to
        compile .pyx files. hostpython is python-for-android's OWN Python, not the build machine's, so
        Cython installed there earlier doesn't count. Best effort: never raises."""
        try:
            hostpython = self.hostpython_location
            if subprocess.run([hostpython, "-c", "import Cython"], capture_output=True).returncode == 0:
                return                                           # already there
            root = os.path.dirname(os.path.dirname(hostpython))
            sites = glob.glob(os.path.join(root, "lib", "python3*", "site-packages"))
            if not sites:
                warning("pygame-ce recipe: no hostpython site-packages under " + root)
                return
            version = os.path.basename(os.path.dirname(sites[0]))[len("python"):]
            command = [sys.executable, "-m", "pip", "install", "--target", sites[0], "--upgrade",
                       "--only-binary=:all:", "--no-deps", "--python-version", version, CYTHON_SPEC]
            info("pygame-ce recipe: hostpython has no Cython; running: " + " ".join(command))
            subprocess.run(command, check=True)
        except Exception as problem:                             # never stop the build for this
            warning(f"pygame-ce recipe: could not provide Cython to hostpython ({problem!r}); going on")

    # ------------------------------------------------------------------ environment

    def get_recipe_env(self, arch):
        env = super().get_recipe_env(arch)
        env["USE_SDL2"] = "1"
        env["PYGAME_CROSS_COMPILE"] = "TRUE"
        env["PYGAME_ANDROID"] = "TRUE"
        return env


recipe = PygameCERecipe()
