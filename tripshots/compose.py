"""Where the reel's window sits on a clip, decided from the frames that actually play in the slot.

The planner frames each shot from its thumbnail: one frame, often from another moment than the part that plays
(a clip trimmed or slipped by hand, a long file cut into several shots, the best window chosen later). Here the
played part is looked at (a few frames across it) and the crop is placed so that:
  - nobody in front is cut by the frame's edge (faces, with their shoulders; the cut-out's figures);
  - a group that fits stays together, else the main person (the biggest face) is held;
  - one person looking sideways gets room in front of them (looking room), not the back of their head;
  - in a crop that cuts top and bottom (an upright clip in a wide or square frame), the eyes sit near the upper
    third and the head isn't cut;
  - a person who moves across the frame is followed, slowly, when one still window can't hold them all along.
Without people, the shot's AI subject is found in those frames (a template match) and held. Nothing reliable
found = None, and the plan's own framing stands. A slot framed by hand (`frame_by: hand`) is never moved.

Results are cached by clip, window and frame shape (~/.tripshots/cache/compose).
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import cv2
import numpy as np

from .config import CACHE_ROOT
from .fx import hdr_chain
from .util import ffmpeg_base

VERSION = 2
WIDTH = 480          # analysis width: big enough for a face of ~10 px in a wide shot
MARGIN = 0.05        # room kept between a person and the frame's edge, as a share of the window
LEAD = 0.12          # looking room: how far a sideways-looking person sits off centre, as a share of the window
MAX_SPEED = 0.18     # a follow moves at most this share of the source's width per second
_det = None


def _cache_dir() -> Path:
    d = CACHE_ROOT / "compose"
    d.mkdir(parents=True, exist_ok=True)
    return d


def window_shape(src_w: float, src_h: float, size: tuple[int, int]) -> tuple[float, float]:
    """The reel's window as a share of the source's (width, height) when the source is scaled to cover the frame."""
    OW, OH = size
    sa, oa = src_w / max(src_h, 1), OW / max(OH, 1)
    return min(1.0, oa / sa), min(1.0, sa / oa)


# ---------------------------------------------------------------- frames and what's in them
def frames(e: dict, length: float, n: int) -> list[tuple[float, np.ndarray]]:
    """n frames spread over the source window [in, in + length], as (seconds into the window, RGB)."""
    w = WIDTH
    h = max(8, int(round(w * float(e["src_h"]) / max(float(e["src_w"]), 1) / 2)) * 2)
    rate = max(0.5, n / max(length, 0.05))
    vf = [f"fps={rate:.4f}", f"scale={w}:{h}:flags=area"] + hdr_chain(
        {"hdr": e.get("hdr"), "transfer": e.get("transfer")}) + ["format=rgb24"]
    cmd = ffmpeg_base() + ["-ss", f"{float(e.get('in', 0.0)):.3f}", "-t", f"{max(0.05, length):.3f}",
                           "-i", str(e["src"]), "-an", "-vf", ",".join(vf), "-frames:v", str(n),
                           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=60).stdout
    except subprocess.TimeoutExpired:
        return []
    k = len(out) // (w * h * 3)
    arr = np.frombuffer(out[: k * w * h * 3], np.uint8).reshape(k, h, w, 3)
    return [(i / rate, arr[i]) for i in range(k)]


def faces(rgb: np.ndarray) -> list[dict]:
    """Faces (normalised x, y, w, h, and yaw: < 0 looking to the picture's left, > 0 to its right). Empty when the
    face model isn't on this computer (it is never downloaded here)."""
    global _det
    try:
        from .people import MODEL_DIR, MODELS
        p = MODEL_DIR / MODELS["yunet"]["file"]
        if not p.exists():
            return []
        if _det is None:
            _det = cv2.FaceDetectorYN.create(str(p), "", (320, 320), 0.7, 0.3, 30)
        h, w = rgb.shape[:2]
        _det.setInputSize((w, h))
        _, rows = _det.detect(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    except Exception:
        return []
    out = []
    for f in rows if rows is not None else []:
        fw, fh = float(f[2]) / w, float(f[3]) / h
        if fw < 0.018:
            continue
        eye_mid, eye_d = (f[4] + f[6]) / 2, abs(f[6] - f[4])
        yaw = float((f[8] - eye_mid) / max(eye_d, 1.0))
        out.append({"x": float(f[0]) / w, "y": float(f[1]) / h, "w": fw, "h": fh, "yaw": yaw,
                    "score": float(f[14])})
    return out


def figures(rgb: np.ndarray) -> list[tuple[float, float, float, float]]:
    """Upright figures (people standing or sitting) from the quick cut-out, as (x0, y0, x1, y1) 0..1."""
    from .nodes import cutout
    m = cutout(rgb)
    if m is None:
        return []
    on = (m > 0.5).astype(np.uint8)
    if not 0.004 < float(on.mean()) < 0.5:
        return []
    h, w = on.shape
    n, _lab, st, _ = cv2.connectedComponentsWithStats(on)
    out = []
    for k in range(1, n):
        x, y, bw, bh, area = st[k]
        if area > 0.003 * on.size and bh >= 1.15 * bw:
            out.append((x / w, y / h, (x + bw) / w, (y + bh) / h))
    return out


def _people(fs: list[dict], figs: list[tuple]) -> list[dict]:
    """Each person in front in one frame: their face, and how wide they are (shoulders, or the figure holding the
    face). Background people (faces under half the biggest one) don't count."""
    if not fs:
        return [{"x0": a, "x1": c, "y0": b, "y1": d, "size": (c - a) * 0.3, "face": None} for a, b, c, d in figs]
    big = max(f["w"] for f in fs)
    out = []
    for f in fs:
        if f["w"] < 0.45 * big:
            continue
        cx = f["x"] + f["w"] / 2
        x0, x1 = f["x"] - 0.9 * f["w"], f["x"] + 1.9 * f["w"]
        for a, b, c, d in figs:  # the cut-out's figure under this face: their arms and whatever they hold
            if a <= cx <= c and c - a <= 5 * f["w"]:
                x0, x1 = min(x0, a), max(x1, c)
        out.append({"x0": x0, "x1": x1, "y0": f["y"] - 0.6 * f["h"], "y1": f["y"] + 2.2 * f["h"],
                    "size": f["w"], "face": f})
    return out


# ---------------------------------------------------------------- the decision
def _span(ps: list[dict]) -> tuple[float, float]:
    return min(p["x0"] for p in ps), max(p["x1"] for p in ps)


def _place(a: float, b: float, cw: float, want: float) -> float:
    """Window centre nearest `want` that keeps [a, b] inside with the margin, and the window inside the picture."""
    m = MARGIN * cw
    lo, hi = b - cw / 2 + m, a + cw / 2 - m
    c = (lo + hi) / 2 if lo > hi else min(max(want, lo), hi)
    return float(min(max(c, cw / 2), 1 - cw / 2))


def decide(samples: list[tuple[float, list[dict]]], cw: float, ch: float, length: float) -> dict | None:
    """Where the window goes, from the people found in each sampled frame: [(seconds into the window, people)]."""
    seen = [(t, ps) for t, ps in samples if ps]
    if not seen or len(seen) < max(1, len(samples) // 3):
        return None   # nobody, or only a passer-by in a few frames: not this shot's subject
    group = all(_span(ps)[1] - _span(ps)[0] <= cw * (1 - 2 * MARGIN) for _t, ps in seen)
    why = "the people in it"
    if not group:   # too many to hold together: the main person
        seen = [(t, [max(ps, key=lambda p: p["size"])]) for t, ps in seen]
        why = "the main person"
    a, b = min(_span(ps)[0] for _t, ps in seen), max(_span(ps)[1] for _t, ps in seen)
    out: dict = {"by": "people", "why": why}
    single = all(len(ps) == 1 for _t, ps in seen)
    look = 0.0
    if single:
        yaws = [ps[0]["face"]["yaw"] for _t, ps in seen if ps[0].get("face")]
        if yaws and abs(float(np.median(yaws))) >= 0.3:
            look = float(np.sign(np.median(yaws)))
    if b - a <= cw * (1 - 2 * MARGIN):   # one still window holds them all the way through
        out["cx"] = round(_place(a, b, cw, (a + b) / 2 + look * LEAD * cw), 4)
        if look:
            out["why"] += ", with room in the direction they look"
    else:   # they move further than the window: follow, slowly
        ts = np.array([t for t, _ps in seen])
        cs = np.array([_place(*_span(ps), cw, (_span(ps)[0] + _span(ps)[1]) / 2 + look * LEAD * cw) for _t, ps in seen])
        if len(cs) >= 3:
            cs = np.convolve(np.pad(cs, 1, mode="edge"), np.ones(3) / 3, mode="valid")
        for i in range(1, len(cs)):
            step = MAX_SPEED * max(ts[i] - ts[i - 1], 1e-3)
            cs[i] = cs[i - 1] + np.clip(cs[i] - cs[i - 1], -step, step)
        out["cx"] = round(float(np.median(cs)), 4)
        out["pts"] = [[round(float(t), 3), round(float(c), 4)] for t, c in zip(ts, cs)]
        out["why"] += ", followed as they move"
    if ch < 0.985:   # the window also cuts top and bottom: eyes near the upper third, the head never cut
        tops = [min(p["y0"] for p in ps) for _t, ps in seen]
        eyes = [float(np.median([p["face"]["y"] + 0.4 * p["face"]["h"] for p in ps if p.get("face")] or
                                [min(p["y0"] for p in ps) + 0.1])) for _t, ps in seen]
        cy = float(np.median(eyes)) + (0.5 - 0.36) * ch
        cy = min(cy, float(min(tops)) + ch / 2 - MARGIN * ch)   # keep the top of the head in
        out["cy"] = round(float(min(max(cy, ch / 2), 1 - ch / 2)), 4)
    out["span"] = [round(a, 4), round(b, 4)]
    return out


def _subject(e: dict, shots: list[tuple[float, np.ndarray]], cw: float) -> dict | None:
    """No people: find the shot's AI subject in the played frames (it was framed on the thumbnail) and hold it."""
    sub = e.get("subject") or {}
    if sub.get("source") != "ai" or not e.get("thumb") or len(shots) < 2:
        return None
    half = (float(sub.get("x1", 0.5)) - float(sub.get("x0", 0.5))) / 2
    if 2 * half * WIDTH < 48:
        return None   # a speck (a far-off person): a match that small lands on whatever looks alike
    from .framing import template_track
    xs = template_track(np.stack([f for _t, f in shots]), e["thumb"], sub)
    if xs is None or float(xs.max() - xs.min()) > max(0.04, cw * 0.15):
        return None   # not found, or it moves: the render's own follow (track) handles that
    c = float(np.median(xs))
    prior = min(max(float(e.get("subject_x", 0.5)), cw / 2), 1 - cw / 2)
    m = MARGIN * cw
    if prior - cw / 2 + m <= c - half and c + half <= prior + cw / 2 - m:
        return None   # the planned window already holds it: leave it be
    return {"by": "subject", "why": "the shot's subject, found in the part that plays",
            "cx": round(_place(c - half, c + half, cw, c), 4)}


def fit(e: dict, length: float, size: tuple[int, int], cache: bool = True) -> dict | None:
    """The framing for this slot's played window (length = source seconds), or None to keep the plan's."""
    if e.get("kind") != "video" or e.get("frame_by") == "hand" or not e.get("src") or not e.get("src_w"):
        return None
    if e.get("layout") not in ("crop", "pan", "fill", None) or e.get("panel"):
        return None
    cw, ch = window_shape(float(e["src_w"]), float(e["src_h"]), size)
    if cw > 0.985 and ch > 0.985:
        return None
    src = str(e["src"])
    try:
        mt = os.path.getmtime(src)
    except OSError:
        return None
    n = 1 if e.get("freeze") else int(min(10, max(4, round(length * 3))))
    sub = e.get("subject") or {}
    key = json.dumps([VERSION, src, mt, round(float(e.get("in", 0)), 3), round(length, 3), n, round(cw, 4),
                      round(ch, 4), e.get("thumb"), [sub.get(k) for k in ("x0", "x1", "source")]])
    path = _cache_dir() / (hashlib.sha1(key.encode()).hexdigest()[:20] + ".json")
    if cache and path.exists():
        try:
            return json.loads(path.read_text()).get("fit")
        except (OSError, ValueError):
            pass
    shots = frames(e, length, n)
    res = None
    if shots:
        cut_at = set(np.linspace(0, len(shots) - 1, min(4, len(shots))).round().astype(int).tolist())
        samples = []
        for i, (t, f) in enumerate(shots):
            fs = faces(f)
            figs = figures(f) if i in cut_at else []
            samples.append((t, _people(fs, figs)))
        res = decide(samples, cw, ch, length) or _subject(e, shots, cw)
    if cache:
        try:
            path.write_text(json.dumps({"fit": res}))
        except OSError:
            pass
    return res


def apply(e: dict, length: float, size: tuple[int, int]) -> dict:
    """The segment's render fields with the framing of its played window (a copy; the plan isn't changed)."""
    try:
        r = fit(e, length, size)
    except Exception:
        r = None
    if not r:
        return e
    e = dict(e)
    if e.get("layout") == "pan" and r.get("by") != "people":
        return e
    if e.get("layout") == "pan":
        e["layout"] = "crop"   # a pan across a view would start or end without the person: hold them instead
    e["subject_x"] = r["cx"]
    sub = dict(e.get("subject") or {})
    sub["cx"] = r["cx"]
    if "cy" in r:
        sub["cy"] = r["cy"]
    e["subject"] = sub
    speed = float(e.get("speed", 1.0)) or 1.0
    pts = [(t / speed, c) for t, c in r["pts"]] if r.get("pts") else None
    if pts and e.get("reverse"):   # the window plays backwards: so does the follow
        end = length / speed
        pts = [(end - t, c) for t, c in reversed(pts)]
    e["_track_pts"] = pts
    e["_framed"] = r
    return e
