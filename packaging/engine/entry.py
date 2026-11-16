"""Entry point of the frozen engine (`tripshots` executable shipped with the desktop app).

The engine archive holds the executable, its libraries and a `bin/` folder with ffmpeg and ffprobe. TripShots calls
`ffmpeg` by name everywhere, so the bundled copies go first on PATH; a system ffmpeg is used when none is bundled.
"""
import multiprocessing
import os
import sys
from pathlib import Path


def _bundled_bin() -> None:
    if not getattr(sys, "frozen", False):
        return
    here = Path(sys.executable).resolve().parent
    for d in (here / "bin", here.parent / "bin"):
        if d.is_dir():
            os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")
            return


LIBPATH = "DYLD_LIBRARY_PATH"


def _text_shaping() -> None:
    """Pillow shapes complex scripts (Malayalam, Hindi, Arabic: vowel signs joined to their letters) with libraqm,
    which opens libfribidi by its bare name at run time. The frozen engine carries its own copy, but macOS only
    looks for a bare name in the folders it was told about when the process started, so Pillow fell back to plain
    layout and split the letters. On a Mac the engine starts itself once more with a folder that holds nothing but
    a link to its own libfribidi on the library path (so nothing else it loads changes), then takes the setting out
    of its environment, so ffmpeg and the other programs it runs never see it."""
    if not getattr(sys, "frozen", False) or sys.platform != "darwin":
        return
    base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    lib = base / "libfribidi.0.dylib"
    if os.environ.get("TRIPSHOTS_SHAPING"):
        os.environ.pop("TRIPSHOTS_SHAPING", None)
        was = os.environ.pop("TRIPSHOTS_LIBPATH_WAS", None)
        if was:
            os.environ[LIBPATH] = was
        else:
            os.environ.pop(LIBPATH, None)
        return
    if not lib.is_file():
        return
    import hashlib
    home = Path(os.environ.get("TRIPSHOTS_HOME") or Path.home() / ".tripshots").expanduser()
    d = home / "cache" / "shaping" / hashlib.sha1(str(lib).encode()).hexdigest()[:12]
    try:
        d.mkdir(parents=True, exist_ok=True)
        link = d / lib.name
        if not link.exists():
            link.symlink_to(lib)
    except OSError:
        return  # can't make the folder: plain layout, as before
    env = dict(os.environ)
    if env.get(LIBPATH):
        env["TRIPSHOTS_LIBPATH_WAS"] = env[LIBPATH]
    env[LIBPATH] = os.pathsep.join([str(d)] + ([env[LIBPATH]] if env.get(LIBPATH) else []))
    env["TRIPSHOTS_SHAPING"] = "1"
    try:
        os.execve(sys.executable, [sys.executable] + sys.argv[1:], env)
    except OSError:
        pass  # can't restart: plain layout, as before


if __name__ == "__main__":
    multiprocessing.freeze_support()
    _bundled_bin()
    _text_shaping()
    from tripshots.cli import main
    main()
