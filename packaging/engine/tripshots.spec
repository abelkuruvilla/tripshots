# PyInstaller recipe for the TripShots engine: one folder (`dist/tripshots/`) with the `tripshots` executable.
# Build:  pyinstaller packaging/engine/tripshots.spec --noconfirm --clean      (run from the repository root)
# A folder starts much faster than a one-file build (nothing is unpacked on every run), which matters because the
# app starts the engine at launch and every job is a new engine process.
# -*- mode: python ; coding: utf-8 -*-
import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
sys.path.insert(0, ROOT)  # this checkout's tripshots, never an older copy installed in the build environment
for name in [m for m in sys.modules if m == "tripshots" or m.startswith("tripshots.")]:
    del sys.modules[name]

datas = collect_data_files("tripshots", includes=["**/*.yaml", "**/*.yml", "**/*.json", "**/*.md", "**/*.ttf",
                                                   "**/*.otf", "**/*.txt", "**/*.cube", "**/*.html", "**/*.js",
                                                   "**/*.css", "**/*.png", "**/*.jpg"])
binaries = []


def _fribidi():
    """Pillow shapes complex scripts with libraqm, which opens libfribidi by name at run time; Pillow's wheels don't
    carry it, so the build machine's copy (brew / apt libfribidi0 / MSYS2 mingw-w64-x86_64-fribidi) goes next to
    the engine, where entry._text_shaping (macOS), PyInstaller's library path (Linux) and its DLL folder (Windows)
    find it."""
    import ctypes.util
    import glob
    names = {"darwin": ["libfribidi.0.dylib"], "linux": ["libfribidi.so.0"],
             "win32": ["libfribidi-0.dll", "fribidi-0.dll"]}.get(sys.platform, [])
    dirs = ["/opt/homebrew/lib", "/usr/local/lib", "/usr/lib/x86_64-linux-gnu", "/usr/lib/aarch64-linux-gnu", "/usr/lib",
            r"C:\msys64\mingw64\bin", r"C:\msys64\ucrt64\bin"]
    for n in names:
        for d in dirs:
            for p in glob.glob(os.path.join(d, n)):
                return os.path.realpath(p), n
        found = ctypes.util.find_library("fribidi")
        if found and os.path.isabs(found):
            return os.path.realpath(found), n
    return None


fb = _fribidi()
if fb:  # copied under the name raqm asks for (the real file may be libfribidi.0.dylib -> .../libfribidi.0.1.0)
    import shutil
    import tempfile
    tmp = os.path.join(tempfile.mkdtemp(), fb[1])
    shutil.copy2(fb[0], tmp)
    binaries.append((tmp, "."))
else:
    print("WARNING: libfribidi not found (brew install fribidi / apt install libfribidi0 / MSYS2 "
          "mingw-w64-x86_64-fribidi): complex scripts won't shape")
hiddenimports = collect_submodules("tripshots")  # commands load modules lazily (and by name: server, mcp_server)

# packages that load parts of themselves at run time (plugins, data files, compiled extensions)
for pkg in ("librosa", "scenedetect", "textual", "mcp", "uvicorn", "yt_dlp", "soundfile", "shapely", "anthropic",
            "onnxruntime", "pillow_heif", "rembg", "google.genai", "opentimelineio", "pooch", "numba", "llvmlite"):
    try:
        d, b, h = collect_all(pkg)
    except Exception:
        continue  # optional extra not installed: that feature is simply off in this build
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    [os.path.join(SPECPATH, "entry.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "IPython", "jupyter", "notebook", "pytest", "torch", "tensorflow"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="tripshots",
    console=True,  # a command-line program: the app starts it hidden, the CLI and MCP talk over stdio
    disable_windowed_traceback=False,
    codesign_identity=os.environ.get("APPLE_SIGNING_IDENTITY") or None,
    entitlements_file=os.path.join(SPECPATH, "entitlements.plist") if sys.platform == "darwin" else None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="tripshots")
