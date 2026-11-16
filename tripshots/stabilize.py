"""Stabilising shaky clips (segment `stabilize`, style `shots.stabilize`: auto | on | off).

A handheld walk or a phone clip shot from a moving car wobbles; in a calm, held shot that reads as a mistake. Before
a shot is rendered, the part of its clip the reel uses (plus a little either side) is stabilised once and cached:

  * vidstab (ffmpeg's libvidstab, two passes: `vidstabdetect` measures the camera's path, `vidstabtransform`
    follows a smoothed version of it and zooms just enough to hide the moving edges) when the ffmpeg in use has it.
    The ffmpeg builds the app ships for Linux and Windows include it; on a Mac, an ffmpeg built with libvidstab.
  * otherwise our own: corners tracked frame to frame at low resolution (Shi-Tomasi + Lucas-Kanade, a RANSAC
    similarity per frame), the camera's path smoothed over about a second, each frame moved back onto the smooth
    path at full resolution and zoomed in a little (at most `MAX_ZOOM`) so no edge ever shows.

Either way the result is an 8-bit SDR clip (HDR sources are tone-mapped first, as the renderer would), cached in
~/.tripshots/cache/stab/ by source, window and method, so editing a plan never stabilises a clip twice. A deliberate
pan or push survives: only the shake (the fast part of the motion) is taken out.

Which shots (planner.mark_stabilize): in `auto`, clips measured as shaky or handheld (shot metrics `shake`, the AI's
"shaky" issue, Gemini's stability) used in calm or held moments (an opening hold, a beatless stretch, a calm
section, the breath before the payoff); never a shot that has an added camera shake on a drop. `on`: every shaky
or handheld clip. `off`: none.
"""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import cv2
import numpy as np

from .config import HOME
from .util import ffmpeg_base, ffprobe, has_filter, log

CACHE = HOME / "cache" / "stab"
VERSION = 2
MAX_ZOOM = 1.12         # the most a frame is zoomed to hide its moving edges (our own method)
SMOOTH_S = 0.9          # how long a stretch of the camera's path is averaged (seconds)
HANDHELD = 0.002        # shot metrics `shake` above this: a handheld wobble
SHAKY = 0.006           # above this: shaky
_vidstab: bool | None = None


def have_vidstab() -> bool:
    global _vidstab
    if _vidstab is None:
        _vidstab = has_filter("vidstabdetect") and has_filter("vidstabtransform")
    return _vidstab


def method() -> str:
    return "vidstab" if have_vidstab() else "opencv"


def needs_it(shot: dict) -> float:
    """How shaky a clip is: 0 = steady, 1 = handheld wobble, 2 = shaky (from every measure there is)."""
    if shot.get("kind") != "video":
        return 0.0
    m = shot.get("metrics") or {}
    a = shot.get("ai") or {}
    w = a.get("watch") or {}
    v = 0.0
    sh = float(m.get("shake", 0) or 0)
    if sh > SHAKY:
        v = 2.0
    elif sh > HANDHELD:
        v = 1.0
    if "shaky" in (a.get("issues") or []):
        v = max(v, 2.0)
    st = w.get("stability")
    if st == "shaky":
        v = max(v, 2.0)
    elif st == "slight_shake":
        v = max(v, 1.0)
    elif st == "steady" and v < 2.0:
        v = min(v, 0.5)   # Gemini watched it and saw it steady: our measure was probably the subject moving
    return v


def _key(src: str, t0: float, dur: float, hdr: bool, transfer: str | None) -> str:
    p = Path(src)
    try:
        st = p.stat()
        sig = f"{p.resolve()}|{st.st_size}|{int(st.st_mtime)}"
    except OSError:
        sig = str(p)
    return hashlib.sha1(f"{sig}|{t0:.3f}|{dur:.3f}|{hdr}|{transfer}|{method()}|{VERSION}".encode()).hexdigest()[:16]


def window(src: str, t0: float, dur: float, hdr: bool = False, transfer: str | None = None) -> Path | None:
    """The clip from t0 for dur seconds, stabilised (cached). None when it couldn't be done (the shot then renders
    from its source, as before)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    out = CACHE / f"{_key(src, t0, dur, hdr, transfer)}.mp4"
    if out.exists() and out.stat().st_size > 0:
        return out
    from .fx import hdr_chain
    pre = hdr_chain({"hdr": hdr, "transfer": transfer})
    tmp = out.with_suffix(".part.mp4")
    try:
        ok = (_vidstab_window if have_vidstab() else _opencv_window)(src, t0, dur, pre, tmp)
    except Exception as e:
        log(f"stabilise: {Path(src).name} failed ({str(e)[:120]}): the shot plays as filmed")
        ok = False
    if not ok or not tmp.exists():
        tmp.unlink(missing_ok=True)
        return None
    tmp.rename(out)
    return out


ENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "14", "-pix_fmt", "yuv420p", "-an"]


def _vidstab_window(src: str, t0: float, dur: float, pre: list[str], out: Path) -> bool:
    trf = out.with_suffix(".trf")
    head = ffmpeg_base() + ["-ss", f"{max(0.0, t0):.3f}", "-t", f"{dur:.3f}", "-i", src, "-an"]
    vf1 = ",".join(pre + [f"vidstabdetect=shakiness=6:accuracy=15:result={trf}"])
    r = subprocess.run(head + ["-vf", vf1, "-f", "null", "-"], capture_output=True, text=True)
    if r.returncode != 0 or not trf.exists():
        return False
    smooth = max(6, int(round(SMOOTH_S * 30 / 2)))   # vidstab counts frames either side
    vf2 = ",".join(pre + [f"vidstabtransform=input={trf}:smoothing={smooth}:optzoom=1:zoomspeed=0.2:interpol=bicubic",
                          "unsharp=5:5:0.4:3:3:0"])
    r = subprocess.run(ffmpeg_base() + ["-y", "-ss", f"{max(0.0, t0):.3f}", "-t", f"{dur:.3f}", "-i", src, "-an",
                                        "-vf", vf2] + ENC + [str(out)], capture_output=True, text=True)
    trf.unlink(missing_ok=True)
    return r.returncode == 0


def _frames(src: str, t0: float, dur: float, pre: list[str], w: int | None = None):
    """Decoded frames (RGB) of the window, at the source's size or `w` wide; yields arrays."""
    info = ffprobe(src)
    vs = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), {})
    W, H = int(vs.get("width") or 0), int(vs.get("height") or 0)
    rot = 0
    for sd in vs.get("side_data_list") or []:
        if "rotation" in sd:
            rot = int(sd["rotation"]) % 180
    if rot:
        W, H = H, W
    if w:
        W, H = w, int(round(w * H / max(W, 1) / 2)) * 2
    vf = ",".join(pre + [f"scale={W}:{H}", "format=rgb24"])
    p = subprocess.Popen(ffmpeg_base() + ["-ss", f"{max(0.0, t0):.3f}", "-t", f"{dur:.3f}", "-i", src, "-an",
                                          "-vf", vf, "-f", "rawvideo", "-"], stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL)
    n = W * H * 3
    try:
        while True:
            b = p.stdout.read(n)
            if len(b) < n:
                break
            yield np.frombuffer(b, np.uint8).reshape(H, W, 3)
    finally:
        p.stdout.close()
        p.wait()


def camera_path(frames) -> np.ndarray:
    """Per frame (dx, dy, angle) of the camera since the first frame, from corners tracked frame to frame."""
    steps = [(0.0, 0.0, 0.0)]
    prev = None
    for fr in frames:
        g = cv2.cvtColor(fr, cv2.COLOR_RGB2GRAY)
        if prev is not None:
            dx = dy = da = 0.0
            pts = cv2.goodFeaturesToTrack(prev, 200, 0.01, 12)
            if pts is not None and len(pts) >= 8:
                nxt, ok, _ = cv2.calcOpticalFlowPyrLK(prev, g, pts, None)
                good = ok.reshape(-1) == 1
                if good.sum() >= 8:
                    m, _ = cv2.estimateAffinePartial2D(pts[good], nxt[good], method=cv2.RANSAC,
                                                       ransacReprojThreshold=2.0)
                    if m is not None:
                        dx, dy, da = float(m[0, 2]), float(m[1, 2]), float(np.arctan2(m[1, 0], m[0, 0]))
            steps.append((dx, dy, da))
        prev = g
    return np.cumsum(np.array(steps, np.float64), axis=0)


def smooth_path(path: np.ndarray, fps: float) -> np.ndarray:
    """The camera's path with the shake taken out: a moving average over SMOOTH_S (edges padded, so a pan that
    runs through the whole clip stays a pan)."""
    r = max(2, int(round(SMOOTH_S * fps / 2)))
    k = np.ones(2 * r + 1) / (2 * r + 1)
    padded = np.pad(path, ((r, r), (0, 0)), mode="edge")
    return np.stack([np.convolve(padded[:, i], k, mode="valid") for i in range(path.shape[1])], 1)


def corrections(path: np.ndarray, fps: float, width: int) -> tuple[np.ndarray, float]:
    """Per-frame (dx, dy, da) that moves each frame onto the smooth path (in pixels of a frame `width` wide), and
    the zoom that hides the edges they reveal. Each frame's move is held within what MAX_ZOOM can hide (a small
    shake is taken out entirely, only the biggest jolts are left partly in), and the zoom is just enough for the
    moves actually made."""
    diff = smooth_path(path, fps) - path
    room = (MAX_ZOOM - 1.0) / 2 * width
    diff[:, :2] = np.clip(diff[:, :2], -room, room)
    diff[:, 2] = np.clip(diff[:, 2], -0.03, 0.03)
    big = float(np.percentile(np.abs(diff[:, :2]), 98)) if len(diff) else 0.0
    zoom = 1.0 + 2 * big / max(width, 1) + 0.01
    return diff, min(MAX_ZOOM, zoom)


def _opencv_window(src: str, t0: float, dur: float, pre: list[str], out: Path) -> bool:
    info = ffprobe(src)
    vs = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), {})
    from .util import parse_rate
    fps = parse_rate(vs.get("avg_frame_rate") or vs.get("r_frame_rate")) or 30.0
    small_w = 480
    path = camera_path(_frames(src, t0, dur, pre, small_w))
    if len(path) < 3:
        return False
    diff, zoom = corrections(path, fps, small_w)
    w = None
    enc = None
    try:
        for i, fr in enumerate(_frames(src, t0, dur, pre)):
            H, W = fr.shape[:2]
            if enc is None:
                k = W / small_w
                w = (W, H, k)
                enc = subprocess.Popen(ffmpeg_base() + ["-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                                                        "-r", f"{fps:.6f}", "-i", "-"] + ENC + [str(out)],
                                       stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
            W, H, k = w
            dx, dy, da = diff[min(i, len(diff) - 1)]
            m = cv2.getRotationMatrix2D((W / 2, H / 2), np.degrees(da), zoom)
            m[0, 2] += dx * k
            m[1, 2] += dy * k
            enc.stdin.write(np.ascontiguousarray(
                cv2.warpAffine(fr, m, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)).tobytes())
    finally:
        if enc is not None:
            enc.stdin.close()
            enc.wait()
    return enc is not None and enc.returncode == 0


PAD = 0.3   # seconds of clip kept either side of what the shot uses (lead-ins, a slip in the editor)


def apply(e: dict, need: float) -> dict:
    """A video segment's fields with its source swapped for the stabilised window it uses (or unchanged)."""
    if not e.get("stabilize") or e.get("kind") not in (None, "video") or not e.get("src"):
        return e
    t0 = max(0.0, float(e.get("in", 0)) - PAD)
    f = window(e["src"], t0, need + 2 * PAD, bool(e.get("hdr")), e.get("transfer"))
    if f is None:
        return e
    return {**e, "src": str(f), "in": round(float(e.get("in", 0)) - t0, 3), "hdr": False, "transfer": None,
            "_stabilized": True}
