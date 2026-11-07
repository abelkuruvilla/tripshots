"""Turn media files into candidate *shots*.

Each video is decoded once at a low frame rate. From those samples we measure
sharpness, exposure, colourfulness, camera motion and shake, split on hard cuts,
and chop long clips into chunks so a 3-minute drone flight yields several
candidate moments. Photos become one shot each.
"""
from __future__ import annotations

import math
import subprocess
from pathlib import Path

import cv2
import numpy as np

from .fx import hdr_chain
from . import library as lib
from .util import debug, ffmpeg_base, hwaccel_args, log, write_json

SAMPLE_FPS = 4
SAMPLE_W = 480
MAX_CHUNK = 8.0
MIN_SHOT = 0.8
ANALYSIS_VERSION = 5  # 5: thumbnail = the shot's best frame


def _colorfulness(rgb: np.ndarray) -> float:
    r, g, b = (rgb[..., i].astype(np.float32) for i in range(3))
    rg, yb = np.abs(r - g), np.abs(0.5 * (r + g) - b)
    return float(np.sqrt(rg.std() ** 2 + yb.std() ** 2) + 0.3 * np.sqrt(rg.mean() ** 2 + yb.mean() ** 2))


def frame_metrics(rgb: np.ndarray) -> dict:
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    return {
        "sharp": float(cv2.Laplacian(gray, cv2.CV_64F).var()),
        "bright": float(gray.mean() / 255.0),
        "clip": float(((gray > 250) | (gray < 5)).mean()),
        "color": _colorfulness(rgb),
    }


def _hist(rgb: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    h = cv2.calcHist([hsv], [0, 1, 2], None, [16, 4, 4], [0, 180, 0, 256, 0, 256])
    return cv2.normalize(h, h).flatten()


def _decode_once(path: str, info: dict, hw: list[str]):
    w = SAMPLE_W
    h = int(round(info["h"] * w / max(info["w"], 1) / 2) * 2) or 270
    vf = [f"fps={SAMPLE_FPS}", f"scale={w}:{h}:flags=area"] + hdr_chain(info) + ["format=rgb24"]
    cmd = ffmpeg_base() + hw + ["-i", path, "-an", "-vf", ",".join(vf),
                                "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    size = w * h * 3
    i = 0
    try:
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            yield i / SAMPLE_FPS, np.frombuffer(buf, np.uint8).reshape(h, w, 3)
            i += 1
    finally:
        proc.stdout.close()
        proc.wait()


def _decode_samples(path: str, info: dict):
    hw = hwaccel_args()
    got = False
    for item in _decode_once(path, info, hw):
        got = True
        yield item
    if not got and hw:  # hardware decode failed: retry in software
        log(f"hw decode failed for {Path(path).name}, retrying in software")
        yield from _decode_once(path, info, [])


def analyze_video(m: dict) -> list[dict]:
    thumbs_dir = lib.THUMBS
    thumbs_dir.mkdir(parents=True, exist_ok=True)
    ts, mets, jpgs, cuts, motion = [], [], [], [], []
    prev_hist = prev_small = None
    win = None
    for t, rgb in _decode_samples(m["path"], m):
        met = frame_metrics(rgb)
        hist = _hist(rgb)
        small = cv2.resize(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY), (160, int(160 * rgb.shape[0] / rgb.shape[1]))
                           ).astype(np.float32)
        if win is None:
            win = cv2.createHanningWindow(small.shape[::-1], cv2.CV_32F)
        if prev_hist is not None:
            corr = cv2.compareHist(prev_hist, hist, cv2.HISTCMP_CORREL)
            if corr < 0.45:
                cuts.append(len(ts))
            (dx, dy), _ = cv2.phaseCorrelate(prev_small, small, win)
            diff = float(np.abs(small - prev_small).mean() / 255.0)
            motion.append((dx / 160.0, dy / 160.0, diff))
        else:
            motion.append((0.0, 0.0, 0.0))
        prev_hist, prev_small = hist, small
        ok, enc = cv2.imencode(".jpg", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 88])
        ts.append(t)
        mets.append(met)
        jpgs.append(enc.tobytes() if ok else b"")
    if not ts:
        return []
    dur = m["duration"] or (ts[-1] + 1 / SAMPLE_FPS)

    # segments between hard cuts, then chunk long ones
    bounds = [0] + cuts + [len(ts)]
    shots = []
    for a, b in zip(bounds[:-1], bounds[1:]):
        t0 = ts[a]
        t1 = ts[b] if b < len(ts) else dur
        seg_len = t1 - t0
        if seg_len < MIN_SHOT:
            continue
        n = max(1, math.ceil(seg_len / MAX_CHUNK))
        step = seg_len / n
        for k in range(n):
            c0, c1 = t0 + k * step, t0 + (k + 1) * step
            idx = [i for i, t in enumerate(ts) if c0 <= t < c1]
            if not idx:
                continue
            shots.append(_build_shot(m, c0, c1, idx, ts, mets, motion, jpgs, thumbs_dir))
    return shots


def _build_shot(m, c0, c1, idx, ts, mets, motion, jpgs, thumbs_dir) -> dict:
    sharp = [mets[i]["sharp"] for i in idx]
    dx = np.array([motion[i][0] for i in idx])
    dy = np.array([motion[i][1] for i in idx])
    diff = np.array([motion[i][2] for i in idx])
    # camera motion: smooth component = intentional pan, residual = shake
    if len(idx) >= 3:
        k = np.ones(3) / 3
        sx = np.convolve(np.pad(dx, 1, mode="edge"), k, "valid")
        sy = np.convolve(np.pad(dy, 1, mode="edge"), k, "valid")
        shake = float(np.median(np.hypot(dx - sx, dy - sy)))
        pan = float(np.median(np.hypot(sx, sy)))
    else:
        shake, pan = 0.0, float(np.median(np.hypot(dx, dy))) if len(idx) else 0.0
    # the frame that stands for the shot (contact sheets for the AI, storyboards): its sharpest, steadiest
    # moment, not just the middle, which may fall in a whip pan or a bump
    jit = np.hypot(dx - dx.mean(), dy - dy.mean()) if len(idx) else np.zeros(0)
    q = [math.log1p(sharp[j]) - 40 * float(jit[j]) for j in range(len(idx))]
    inner = range(1, len(idx) - 1) if len(idx) > 2 else range(len(idx))  # avoid the cut frames themselves
    best = idx[max(inner, key=lambda j: q[j])] if len(idx) else idx[0]
    thumb = thumbs_dir / f"{m['sig']}_{int(c0 * 1000):08d}b.jpg"  # "b": best frame (version 5)
    if not thumb.exists():
        thumb.write_bytes(jpgs[best])
    return {
        "kind": "video", "src": m["path"], "sig": m["sig"], "name": m["name"],
        "t0": round(c0, 3), "t1": round(c1, 3), "dur": round(c1 - c0, 3),
        "fps": m["fps"], "w": m["w"], "h": m["h"], "hdr": m["hdr"], "transfer": m.get("transfer"),
        "created": m.get("created"), "gps": m.get("gps"), "thumb": str(thumb),
        "metrics": {
            "sharp": float(np.median(sharp)), "bright": float(np.mean([mets[i]["bright"] for i in idx])),
            "clip": float(np.mean([mets[i]["clip"] for i in idx])),
            "color": float(np.median([mets[i]["color"] for i in idx])),
            "pan": pan, "shake": shake, "activity": float(np.median(diff)),
        },
        # per-sample timeline (seconds relative to source) used to pick the best window
        "samples": {"t": [round(ts[i], 3) for i in idx], "sharp": [round(s, 2) for s in sharp],
                    "jitter": [round(float(v), 5) for v in np.hypot(dx - dx.mean(), dy - dy.mean())]},
    }


def analyze_photo(m: dict) -> dict:
    img = cv2.imread(m["still"])
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    small = cv2.resize(rgb, (SAMPLE_W, int(SAMPLE_W * h / w)), interpolation=cv2.INTER_AREA)
    met = frame_metrics(small)
    thumb = lib.THUMBS / f"{m['sig']}_photo.jpg"
    thumb.parent.mkdir(parents=True, exist_ok=True)
    if not thumb.exists():
        cv2.imwrite(str(thumb), cv2.cvtColor(small, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 88])
    return {
        "kind": "photo", "src": m["path"], "still": m["still"], "sig": m["sig"], "name": m["name"],
        "t0": 0.0, "t1": None, "dur": None, "fps": None, "w": m["w"], "h": m["h"], "hdr": False,
        "created": m.get("created"), "gps": m.get("gps"), "thumb": str(thumb),
        "metrics": {**met, "pan": 0.0, "shake": 0.0, "activity": 0.0},
        "samples": None,
    }




def _fresh(shots: list[dict], m: dict) -> list[dict]:
    out = []
    for s in shots:
        s = dict(s)
        s.update({"src": m["path"], "name": m["name"], "created": m.get("created"), "gps": m.get("gps")})
        if s["kind"] == "photo":
            s["still"] = m["still"]
        out.append(s)
    return out


def analyze(media: list[dict], work: Path) -> list[dict]:
    """Shot analysis per file, stored permanently in the library (decoded once, ever)."""
    out: list[dict] = []
    todo = []
    for m in media:
        cached = lib.get_shots(m["sig"], ANALYSIS_VERSION)
        if cached is not None and all(Path(s["thumb"]).exists() for s in cached):
            out.extend(_fresh(cached, m))
        else:
            todo.append(m)
    if todo:
        log(f"analyzing {len(todo)} new file(s); {len(media) - len(todo)} already in the library")
    for n, m in enumerate(todo, 1):
        log(f"analyzing {n}/{len(todo)}: {m['name']}")
        try:
            shots = analyze_video(m) if m["kind"] == "video" else [analyze_photo(m)]
        except Exception as e:  # not stored: a disconnected drive shouldn't poison the library
            log(f"  failed: {e}")
            continue
        if shots or m["kind"] == "photo":
            lib.put_shots(m["sig"], ANALYSIS_VERSION, shots)
        out.extend(_fresh(shots, m))
    # stable ids in capture order
    out.sort(key=lambda s: (s.get("created") or "", s["src"], s["t0"]))
    for i, s in enumerate(out, 1):
        s["id"] = f"S{i:03d}"
    write_json(work / "shots.json", out)
    log(f"{len(out)} candidate shots")
    debug(f"shots written to {work / 'shots.json'}")
    return out


def heuristic_scores(shots: list[dict]) -> dict[str, dict]:
    """Fallback quality score (1-10) from technical metrics only."""
    if not shots:
        return {}
    ls = np.array([math.log1p(s["metrics"]["sharp"]) for s in shots])
    col = np.array([s["metrics"]["color"] for s in shots])
    z = lambda a: (a - a.mean()) / (a.std() + 1e-6)  # noqa: E731
    zs, zc = z(ls), z(col)
    out = {}
    for i, s in enumerate(shots):
        m = s["metrics"]
        score = 6.0 + 1.2 * zs[i] + 0.8 * zc[i]
        score -= 3.0 * max(0.0, m["clip"] - 0.15)
        if m["bright"] < 0.1 or m["bright"] > 0.88:  # dusk/night scenery is fine
            score -= 1.5
        score -= min(3.0, max(0.0, m["shake"] - 0.002) * 250)
        if s["kind"] == "video" and 0.002 < m["pan"] < 0.03:
            score += 0.5  # smooth camera movement reads well on reels
        out[s["id"]] = {
            "score": round(float(max(1.0, min(10.0, score))), 1), "usable": score >= 3.5,
            "tags": [], "subject_x": 0.5, "role": "any",
            "mood": "dynamic" if (m["pan"] > 0.01 or m["activity"] > 0.03) else "calm",
            "motion": "static" if m["pan"] < 0.002 else "pan", "note": "heuristic", "source": "heuristic",
        }
    return out
