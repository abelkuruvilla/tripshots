"""Reference reels recorded off a phone screen, made usable before anything measures them.

A screen recording of an Instagram reel is the reel inside the phone's interface: a status bar, the app's
buttons, the caption and the like counts sit still above and below the moving picture, and the file has the
phone's shape (about 9:19.5), not the reel's. Measured as it is, its shots, colours and text would be the
interface's. `clean(path)`:
  * finds the moving picture: the rows that change over time (per-row standard deviation over a dozen frames),
    and when the file has a phone's shape and its still edges are interface (not plain black), cuts the reel's
    9:16 window around it (a letterbox inside the reel is part of its look and stays)
  * fixes phase-cancelled sound: some recordings carry left and right in opposite phase, so a mono mix (what the
    beat tracker hears) all but vanishes. When the mix is 10 dB quieter than the louder side, one side is used
Returns the cleaned copy (cached in ~/.tripshots/learn/clean/), or the file itself when nothing needs fixing.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

from .config import HOME
from .util import ffmpeg_base, ffprobe, file_sig, log, read_json, write_json

CLEAN = HOME / "learn" / "clean"
REEL_AR = 9 / 16


def _frames(path: Path, dur: float, w: int = 90, n: int = 12) -> np.ndarray | None:
    info = ffprobe(path)
    vs = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), {})
    W, H = int(vs.get("width") or 0), int(vs.get("height") or 0)
    if not W or not H:
        return None
    h = int(round(w * H / W / 2)) * 2
    out = []
    for t in np.linspace(0.08, 0.92, n) * dur:
        p = subprocess.run(ffmpeg_base() + ["-ss", f"{t:.2f}", "-i", str(path), "-frames:v", "1", "-an",
                                            "-vf", f"scale={w}:{h},format=gray", "-f", "rawvideo", "-"],
                           capture_output=True)
        if len(p.stdout) >= w * h:
            out.append(np.frombuffer(p.stdout[: w * h], np.uint8).reshape(h, w))
    return np.stack(out).astype(np.float32) if len(out) >= 6 else None


def _band(std: np.ndarray) -> tuple[int, int]:
    """The longest run of moving rows (or columns)."""
    moving = std > max(6.0, 0.35 * float(std.max()))
    best, cur, start = (0, len(std)), 0, 0
    run_best = 0
    for i, m in enumerate(list(moving) + [False]):
        if m:
            if cur == 0:
                start = i
            cur += 1
        else:
            if cur > run_best:
                run_best, best = cur, (start, i)
            cur = 0
    return best


def picture_box(path: Path, dur: float) -> tuple[float, float, float, float] | None:
    """(x0, y0, x1, y1) of the reel inside a screen recording, as shares of the frame; None for a plain reel.

    A phone shows a reel at the screen's full width, 9:16, with the interface above and below it. The reel's
    window is put around the moving picture (centred on it: a letterboxed reel's still black bars are part of
    the reel and stay inside), and only when the still edges of the screen are interface (not plain black)."""
    fr = _frames(path, dur)
    if fr is None:
        return None
    n, h, w = fr.shape
    if w / h > REEL_AR - 0.035:  # a reel's own shape (or wider): not a phone screen
        return None
    rows = fr.std(axis=0).mean(axis=1)
    y0, y1 = _band(rows)
    if (y1 - y0) < 0.2 * h:
        return None
    edge = max(2, int(0.05 * h))

    def interface(a: np.ndarray) -> bool:  # still, and not plain black: the status bar, buttons, text, counts
        return float(a.std(axis=0).mean()) < 4 and (float(a.mean()) > 22 or float(a.std()) > 10)
    if not (interface(fr[:, :edge]) or interface(fr[:, h - edge:])):
        return None
    win = min(float(h), max(float(y1 - y0), w / REEL_AR))
    c = (y0 + y1) / 2
    top = min(max(0.0, c - win / 2), h - win)
    return 0.0, top / h, 1.0, (top + win) / h


def phase_cancelled(path: Path) -> bool:
    """Left and right in opposite phase: the mono mix is 10 dB quieter than the louder side."""
    p = subprocess.run(ffmpeg_base() + ["-i", str(path), "-vn", "-ac", "2", "-ar", "11025", "-t", "60",
                                        "-f", "f32le", "-"], capture_output=True)
    a = np.frombuffer(p.stdout, np.float32)
    if len(a) < 11025 * 2:
        return False
    st = a[: len(a) // 2 * 2].reshape(-1, 2)
    rms = lambda x: float(np.sqrt(np.mean(x ** 2)) + 1e-9)
    side = max(rms(st[:, 0]), rms(st[:, 1]))
    if 20 * np.log10(side) < -45:  # silent: nothing to fix
        return False
    return 20 * np.log10(rms(st.mean(axis=1)) / side) < -10


def clean(path: Path) -> Path:
    try:
        return _clean(Path(path))
    except Exception as e:  # never in the way: a file that can't be checked is measured as it is
        log(f"reference clean-up skipped for {Path(path).name} ({str(e)[:80]})")
        return Path(path)


def _clean(path: Path) -> Path:
    sig = file_sig(path)
    CLEAN.mkdir(parents=True, exist_ok=True)
    note_p = CLEAN / f"{sig}.json"
    note = read_json(note_p)
    if note is not None:
        out = Path(note.get("file") or "")
        return out if note.get("file") and out.exists() else path
    info = ffprobe(path)
    dur = float(info.get("format", {}).get("duration") or 0)
    has_audio = any(s.get("codec_type") == "audio" for s in info.get("streams", []))
    box = picture_box(path, dur) if dur > 1 else None
    flip = has_audio and phase_cancelled(path)
    if not box and not flip:
        write_json(note_p, {"file": None})
        return path
    out = CLEAN / f"{sig}.mp4"
    vf = []
    if box:
        x0, y0, x1, y1 = box
        vf.append(f"crop=trunc(iw*{x1 - x0:.4f}/2)*2:trunc(ih*{y1 - y0:.4f}/2)*2:trunc(iw*{x0:.4f}):trunc(ih*{y0:.4f})")
    cmd = ffmpeg_base() + ["-y", "-i", str(path)] + (["-vf", ",".join(vf)] if vf else []) + \
        ["-c:v", "libx264", "-crf", "16", "-preset", "veryfast", "-g", "12", "-pix_fmt", "yuv420p"]
    cmd += (["-af", "pan=stereo|c0=c0|c1=c0", "-c:a", "aac", "-b:a", "192k"] if flip else
            (["-c:a", "aac", "-b:a", "192k"] if has_audio else ["-an"])) + [str(out)]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0 or not out.exists():
        log(f"reference clean-up failed for {path.name}: measuring it as it is")
        write_json(note_p, {"file": None})
        return path
    what = ([f"cut to the picture inside the phone's screen ({(box[2] - box[0]) * 100:.0f}% x "
             f"{(box[3] - box[1]) * 100:.0f}%)"] if box else []) + (["sound fixed (left and right cancelled out)"] if flip else [])
    log(f"{path.name}: a screen recording: " + ", ".join(what))
    write_json(note_p, {"file": str(out), "box": box, "phase_fixed": flip, "source": str(path)})
    return out
