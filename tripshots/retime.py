"""Speed effects: slow motion, speed-ups and speed ramps, with the maths shared by the planner, the renderer,
the sound design and the exports.

A segment's speed is either constant (`speed`: 0.5 = half speed, 2 = twice as fast) or a ramp (`ramp`: a
named curve, or `ramp_points`), with the moment that matters (`ramp_hit`, seconds from the start of the
segment, usually a beat) where the curve slams into slow motion.

Ramps (speed over the shot, 1 = real time):

  velocity  rush in at 2.6x, slam into slow motion (0.35x) on the hit, speed back out     the "velocity edit"
  slam      real time, then slow motion (0.3x) from the hit to the end                    a landing, a jump, a wave
  bullet    real time, a slow-motion hold (0.22x) around the hit, back to real time       a moment frozen in passing
  rush      real time, then speeds up to 3.2x into the next cut                           builds into a drop / whip
  impact    starts in slow motion (0.3x) and picks up to real time                        the shot right after a drop
  surge     slow start (0.6x), takes off to 2.4x                                          driving, flying, running

Slow motion is smooth when the clip was shot at 50 fps or more. Slower than that, in-between frames are made
with optical flow (`smooth: flow`, the default), by cross-fading neighbouring frames (`blend`) or not at all
(`off`). Speed-ups average the frames they skip over, like a camera's motion blur.
"""
from __future__ import annotations

import math

KINDS = ("velocity", "slam", "bullet", "rush", "impact", "surge")
# where the hit falls by default (fraction of the shot), for curves that have one
DEFAULT_HIT = {"velocity": 0.4, "slam": 0.45, "bullet": 0.4}
SMOOTH = ("flow", "blend", "off")
SPEED_MIN, SPEED_MAX = 0.2, 4.0


def keys(kind: str, hit: float | None = None, points: list | None = None) -> list[tuple[float, float]]:
    """Keyframes (u 0..1 across the shot, speed) of a ramp. `hit` is a fraction of the shot."""
    if points:
        pts = sorted((max(0.0, min(1.0, float(u))), max(SPEED_MIN, min(SPEED_MAX, float(s)))) for u, s in points)
        if pts[0][0] > 0:
            pts.insert(0, (0.0, pts[0][1]))
        if pts[-1][0] < 1:
            pts.append((1.0, pts[-1][1]))
        return pts
    h = DEFAULT_HIT.get(kind, 0.4) if hit is None else hit
    if kind == "velocity":
        h = max(0.2, min(0.7, h))
        return [(0, 2.6), (h - 0.16, 2.6), (h, 0.35), (min(h + 0.32, 0.88), 0.35), (1, 1.8)]
    if kind == "slam":
        h = max(0.15, min(0.8, h))
        return [(0, 1.0), (h - 0.12, 1.0), (h, 0.3), (1, 0.4)]
    if kind == "bullet":
        h = max(0.15, min(0.6, h))
        return [(0, 1.0), (h - 0.1, 1.0), (h, 0.22), (h + 0.28, 0.22), (min(1.0, h + 0.42), 1.0), (1, 1.0)]
    if kind == "rush":
        return [(0, 1.0), (0.45, 1.0), (1, 3.2)]
    if kind == "impact":
        return [(0, 0.3), (0.45, 0.3), (1, 1.3)]
    if kind == "surge":
        return [(0, 0.6), (0.3, 0.6), (1, 2.4)]
    raise ValueError(f"unknown speed ramp '{kind}' (use one of {', '.join(KINDS)} or ramp_points)")


def speed_at(k: list[tuple[float, float]], u: float) -> float:
    """Speed at u (0..1), eased (cosine) between keyframes."""
    u = max(0.0, min(1.0, u))
    for (u0, s0), (u1, s1) in zip(k, k[1:]):
        if u <= u1:
            q = 0.0 if u1 <= u0 else (u - u0) / (u1 - u0)
            return s0 + (s1 - s0) * (0.5 - 0.5 * math.cos(math.pi * q))
    return k[-1][1]


def seg_keys(seg: dict, length: float | None = None, lead: float = 0.0) -> list[tuple[float, float]]:
    """Keyframes for a segment. With `length`/`lead` (render: the shot plus transition overlap) the hit
    stays at the same moment on the timeline."""
    dur = float(seg["dur"])
    length = length or dur
    if seg.get("ramp") in (None, "", "none"):
        s = float(seg.get("speed", 1.0) or 1.0)
        return [(0.0, s), (1.0, s)]
    hit = seg.get("ramp_hit")
    h = None if hit is None else (lead + float(hit)) / max(1e-6, length)
    return keys(seg["ramp"], h, seg.get("ramp_points"))


def positions(k: list[tuple[float, float]], n: int, src_rate: float, out_rate: float) -> list[float]:
    """Source frame (fractional, at src_rate) shown at each of n output frames (at out_rate)."""
    pos, p = [], 0.0
    step = src_rate / out_rate
    for i in range(n):
        if i:
            p += speed_at(k, (i - 0.5) / max(1, n - 1)) * step
        pos.append(p)
    return pos


def source_seconds(seg: dict, length: float | None = None) -> float:
    """Seconds of source footage a segment plays (a ramp may use more or less than its duration)."""
    length = length or float(seg["dur"])
    if seg.get("ramp") in (None, "", "none"):
        return length * float(seg.get("speed", 1.0) or 1.0)
    k = seg_keys(seg, length)
    n = 64
    return length * sum(speed_at(k, (i + 0.5) / n) for i in range(n)) / n


def hit_time(seg: dict) -> float | None:
    """Where a ramp slams into slow motion, in seconds on the reel (None if it has no hit)."""
    r = seg.get("ramp")
    if not r or r == "none":
        return None
    if seg.get("ramp_points"):
        k = keys("", points=seg["ramp_points"])
        drops = [(k[i + 1][0], k[i][1] - k[i + 1][1]) for i in range(len(k) - 1)]
        u, d = max(drops, key=lambda x: x[1])
        return float(seg["out_start"]) + u * float(seg["dur"]) if d > 0.5 else None
    if r not in DEFAULT_HIT:
        return None
    h = seg.get("ramp_hit")
    return float(seg["out_start"]) + (float(h) if h is not None else DEFAULT_HIT[r] * float(seg["dur"]))


def describe(seg: dict, short: bool = False) -> str:
    """Label for exports ('0.5x', '2x', 'velocity ramp'); short=True for storyboard tiles ('slam')."""
    if seg.get("ramp_points"):
        return "custom" if short else "custom ramp"
    if seg.get("ramp"):
        return seg["ramp"] if short else f"{seg['ramp']} ramp"
    s = float(seg.get("speed", 1.0) or 1.0)
    return "" if abs(s - 1) < 0.01 else f"{s:g}x"


def needs_retime(seg: dict, src_fps: float | None) -> bool:
    """True when the segment goes through the frame-by-frame retimer (ramps, or slow motion that needs
    made-up in-between frames) rather than ffmpeg's plain speed change."""
    if seg.get("ramp"):
        return True
    s = float(seg.get("speed", 1.0) or 1.0)
    smooth = seg.get("smooth", "flow")
    return s < 0.97 and smooth in ("flow", "blend") and (src_fps or 30) * s < 29


def interp_flow(fa, fb, a: float, cache: dict | None = None, key=None):
    """Frame between fa and fb at fraction a, warped along optical flow (OpenCV DIS) from both sides."""
    import cv2
    import numpy as np
    h, w = fa.shape[:2]
    fl = cache.get(key) if cache is not None and key is not None else None
    if fl is None:
        sc = 0.5 if w * h > 600_000 else 1.0
        ga = cv2.cvtColor(cv2.resize(fa, None, fx=sc, fy=sc, interpolation=cv2.INTER_AREA), cv2.COLOR_RGB2GRAY)
        gb = cv2.cvtColor(cv2.resize(fb, None, fx=sc, fy=sc, interpolation=cv2.INTER_AREA), cv2.COLOR_RGB2GRAY)
        dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
        fab, fba = dis.calc(ga, gb, None), dis.calc(gb, ga, None)
        if sc != 1.0:
            fab = cv2.resize(fab, (w, h), interpolation=cv2.INTER_LINEAR) / sc
            fba = cv2.resize(fba, (w, h), interpolation=cv2.INTER_LINEAR) / sc
        fl = (fab, fba)
        if cache is not None and key is not None:
            cache[key] = fl
    fab, fba = fl
    gx, gy = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    wa = cv2.remap(fa, gx - a * fab[..., 0], gy - a * fab[..., 1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    wb = cv2.remap(fb, gx - (1 - a) * fba[..., 0], gy - (1 - a) * fba[..., 1], cv2.INTER_LINEAR,
                   borderMode=cv2.BORDER_REPLICATE)
    return cv2.addWeighted(wa, 1 - a, wb, a, 0)
