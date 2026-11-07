"""Shared fixtures: an isolated TRIPSHOTS_HOME and synthetic footage made with ffmpeg (no real clips needed)."""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

_HOME = Path(tempfile.mkdtemp(prefix="tripshots-test-"))
os.environ["TRIPSHOTS_HOME"] = str(_HOME)  # before any tripshots import: never touch the real library
os.environ["TRIPSHOTS_OFFLINE"] = "1"
os.environ["TRIPSHOTS_BACKEND"] = "none"
os.environ.pop("GEMINI_API_KEY", None)

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")


def ff(*args):
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *map(str, args)], check=True)


def clip(path: Path, src: str = "testsrc2", dur: float = 4, size: str = "1280x720", audio: str | None = None):
    a = ["-f", "lavfi", "-i", audio] if audio else []
    ff("-f", "lavfi", "-i", (f"{src}:s={size}:r=30" if "=" in src else f"{src}=s={size}:r=30"), *a, "-t", dur, "-pix_fmt", "yuv420p",
       "-c:v", "libx264", "-preset", "ultrafast", *(["-c:a", "aac"] if audio else []), path)
    return path


@pytest.fixture(scope="session")
def footage(tmp_path_factory):
    """Four short landscape clips with different pictures, one photo, plus camera clutter."""
    d = tmp_path_factory.mktemp("foot")
    clip(d / "DJI_20260501123000_0001_D.MP4", "testsrc2")
    clip(d / "VID_20260501_124500.mp4", "smptehdbars")
    clip(d / "GX010042.MP4", "mandelbrot")
    clip(d / "PXL_20260501_130000123.mp4", "cellauto=rule=110")
    ff("-f", "lavfi", "-i", "testsrc=s=1600x1200", "-frames:v", "1", d / "IMG_20260501_131500.jpg")
    (d / "GX010042.LRV").write_bytes(b"low-res preview")
    (d / "VID_20260501_140000_00_001.insv").write_bytes(b"raw 360")
    return d


@pytest.fixture(scope="session")
def song(tmp_path_factory):
    """20 s of 120 BPM clicks over a soft pad: a beat grid librosa can find."""
    p = tmp_path_factory.mktemp("music") / "song.wav"
    ff("-f", "lavfi", "-i", "sine=f=1000:d=0.03,apad=pad_dur=0.47", "-f", "lavfi", "-i", "sine=f=220:d=20",
       "-filter_complex", "[0]aloop=loop=39:size=24000[c];[c][1]amix=inputs=2:duration=longest,volume=2",
       "-ar", "48000", "-t", "20", p)
    return p
