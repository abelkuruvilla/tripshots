"""Video encoder choice: the GPU / media engine when there is one, libx264 otherwise.

TRIPSHOTS_ENCODER (or `--encoder`): auto (default) | hardware | software | videotoolbox | nvenc | qsv
- auto: Apple VideoToolbox on a Mac, NVIDIA NVENC or Intel Quick Sync elsewhere, each only after a
  real test encode at 1080x1920 succeeds; otherwise libx264.
- hardware: the same, but says so loudly when no hardware encoder works.
- software: always libx264 (best quality per megabyte, slowest).

Two profiles: "segment" (intermediate clips the compositor reads back: high bitrate, fast) and
"final" (the reel you upload: high quality, capped at 25 Mbit/s like before).
If a hardware encode fails mid-render, `disable()` switches the rest of the run to libx264.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import threading
from pathlib import Path

import numpy as np

from .config import OUT_FPS, OUT_H, OUT_W
from .util import ffmpeg_base, is_mac, log

SOFTWARE = {
    "segment": ["-c:v", "libx264", "-preset", "fast", "-crf", "14", "-pix_fmt", "yuv420p"],
    "final": ["-c:v", "libx264", "-preset", "medium", "-crf", "17", "-maxrate", "25M", "-bufsize", "50M",
              "-profile:v", "high", "-pix_fmt", "yuv420p"],
}

# per encoder: candidate arg sets, tried in order (constant quality first; plain bitrate as fallback
# for older chips / ffmpeg builds that reject the quality option)
HARDWARE = {
    "videotoolbox": {
        "name": "Apple VideoToolbox",
        "segment": [["-c:v", "h264_videotoolbox", "-q:v", "80", "-profile:v", "high", "-pix_fmt", "yuv420p"],
                    ["-c:v", "h264_videotoolbox", "-b:v", "40M", "-profile:v", "high", "-pix_fmt", "yuv420p"]],
        "final": [["-c:v", "h264_videotoolbox", "-q:v", "65", "-maxrate", "25M", "-bufsize", "50M",
                   "-profile:v", "high", "-pix_fmt", "yuv420p"],
                  ["-c:v", "h264_videotoolbox", "-b:v", "16M", "-maxrate", "25M", "-bufsize", "50M",
                   "-profile:v", "high", "-pix_fmt", "yuv420p"]],
    },
    "nvenc": {
        "name": "NVIDIA NVENC",
        "segment": [["-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", "14", "-b:v", "0",
                     "-pix_fmt", "yuv420p"]],
        "final": [["-c:v", "h264_nvenc", "-preset", "p6", "-tune", "hq", "-rc", "vbr", "-cq", "19", "-b:v", "0",
                   "-maxrate", "25M", "-bufsize", "50M", "-profile:v", "high", "-pix_fmt", "yuv420p"]],
    },
    "qsv": {
        "name": "Intel Quick Sync",
        "segment": [["-c:v", "h264_qsv", "-global_quality", "16", "-pix_fmt", "nv12"]],
        "final": [["-c:v", "h264_qsv", "-preset", "slow", "-global_quality", "20", "-maxrate", "25M",
                   "-bufsize", "50M", "-profile:v", "high", "-pix_fmt", "nv12"]],
    },
}

_lock = threading.Lock()
_choice: dict | None = None  # {"key", "name", "segment", "final", "why"}


def mode() -> str:
    return (os.environ.get("TRIPSHOTS_ENCODER") or "auto").strip().lower()


def _listed() -> set[str]:
    try:
        out = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    except FileNotFoundError:
        return set()
    return {ln.split()[1] for ln in out.splitlines() if len(ln.split()) > 1}


def _works(args: list[str]) -> bool:
    """A real test: 10 frames at the reel's size through the encoder into an mp4."""
    frames = (np.random.default_rng(0).integers(0, 255, (10, OUT_H, OUT_W, 3), dtype=np.uint8)).tobytes()
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "t.mp4"
        cmd = ffmpeg_base() + ["-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{OUT_W}x{OUT_H}", "-r", str(OUT_FPS),
                               "-i", "-"] + args + ["-r", str(OUT_FPS), str(out)]
        try:
            p = subprocess.run(cmd, input=frames, capture_output=True, timeout=60)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False
        return p.returncode == 0 and out.exists() and out.stat().st_size > 1000


def _candidates(m: str) -> list[str]:
    if m in HARDWARE:
        return [m]
    return ["videotoolbox"] if is_mac() else ["nvenc", "qsv"]


def choose(force: bool = False) -> dict:
    """Pick (and test) the encoder once per process."""
    global _choice
    with _lock:
        if _choice is not None and not force:
            return _choice
        m = mode()
        soft = {"key": "software", "name": "libx264 (software)", **SOFTWARE}
        if m in ("software", "x264", "libx264", "off", "0"):
            _choice = {**soft, "why": "set to software"}
            return _choice
        listed, tried = _listed(), []
        for key in _candidates(m):
            hw = HARDWARE[key]
            if hw["segment"][0][1] not in listed:
                tried.append(f"{hw['name']}: not in this ffmpeg build")
                continue
            seg = next((a for a in hw["segment"] if _works(a)), None)
            fin = next((a for a in hw["final"] if _works(a)), None) if seg else None
            if seg and fin:
                _choice = {"key": key, "name": hw["name"], "segment": seg, "final": fin, "why": "tested ok"}
                return _choice
            tried.append(f"{hw['name']}: test encode failed (no such hardware or driver)")
        why = "; ".join(tried) or "no hardware encoder for this system"
        if m != "auto":
            log(f"hardware encoding unavailable ({why}); using libx264")
        _choice = {**soft, "why": why}
        return _choice


def args(profile: str) -> list[str]:
    """Encoder args for 'segment' or 'final' (frame rate added by the caller)."""
    return list(choose()[profile])


def using_hardware() -> bool:
    return choose()["key"] != "software"


def disable(reason: str) -> None:
    """A hardware encode failed for real: use libx264 for the rest of this run."""
    global _choice
    with _lock:
        if _choice and _choice["key"] != "software":
            log(f"{_choice['name']} failed ({reason.strip()[:160]}); switching to libx264 for this render")
        _choice = {"key": "software", "name": "libx264 (software)", **SOFTWARE, "why": f"fallback: {reason[:80]}"}


def describe() -> str:
    c = choose()
    return c["name"] if c["key"] != "software" else f"libx264 (software; {c['why']})"
