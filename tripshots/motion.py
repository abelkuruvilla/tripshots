"""Frame-level motion and transitions (numpy + OpenCV), all deterministic.

Transitions are centred on the cut (which sits on a beat): p=0 is the start of the
transition window, p=0.5 the beat, p=1 the end. Each takes the outgoing frame A and
incoming frame B (both 1080x1920 RGB uint8) and returns the composited frame.

Per-shot motion (beat "punch" zooms, drop shake, slow push) is a single affine warp
applied to a frame before it is composited.
"""
from __future__ import annotations

import math

import cv2
import numpy as np

# ------------------------------------------------------------------ easing
def ease_in(p: float) -> float:
    return p ** 3


def ease_out(p: float) -> float:
    return 1 - (1 - p) ** 3


def ease_in_out(p: float) -> float:
    return 4 * p ** 3 if p < 0.5 else 1 - (-2 * p + 2) ** 3 / 2


def _clip(p: float) -> float:
    return 0.0 if p < 0 else 1.0 if p > 1 else p


# --------------------------------------------------------------- transforms
def affine(img: np.ndarray, scale: float = 1.0, angle: float = 0.0, tx: float = 0.0, ty: float = 0.0,
           border=cv2.BORDER_REFLECT) -> np.ndarray:
    """Zoom/rotate about the centre, then translate (pixels). Identity is returned untouched."""
    if abs(scale - 1) < 1e-4 and abs(angle) < 1e-3 and abs(tx) < 0.05 and abs(ty) < 0.05:
        return img
    h, w = img.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, scale)
    M[0, 2] += tx
    M[1, 2] += ty
    return cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=border)


def motion_blur(img: np.ndarray, length: int, horizontal: bool = True) -> np.ndarray:
    length = int(length)
    if length < 3:
        return img
    k = np.zeros((length, length), np.float32)
    if horizontal:
        k[length // 2, :] = 1.0 / length
    else:
        k[:, length // 2] = 1.0 / length
    # blur at half resolution: 4x cheaper and visually identical for a fast whip
    h, w = img.shape[:2]
    small = cv2.resize(img, (w // 2, h // 2), interpolation=cv2.INTER_AREA)
    k2 = max(3, length // 2)
    ks = np.zeros((k2, k2), np.float32)
    if horizontal:
        ks[k2 // 2, :] = 1.0 / k2
    else:
        ks[:, k2 // 2] = 1.0 / k2
    small = cv2.filter2D(small, -1, ks, borderType=cv2.BORDER_REFLECT)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)


def zoom_blur(img: np.ndarray, base: float, amount: float, taps: int = 5) -> np.ndarray:
    """Radial blur: average of the frame zoomed between base and base*(1+amount)."""
    if amount < 0.01:
        return affine(img, base)
    h, w = img.shape[:2]
    small = cv2.resize(img, (w // 2, h // 2), interpolation=cv2.INTER_AREA)
    acc = np.zeros(small.shape, np.float32)
    for i in range(taps):
        acc += affine(small, base * (1 + amount * i / (taps - 1)))
    out = (acc / taps).astype(np.uint8)
    return cv2.resize(out, (w, h), interpolation=cv2.INTER_LINEAR)


def blend(a: np.ndarray, b: np.ndarray, t: float) -> np.ndarray:
    t = _clip(t)
    if t <= 0:
        return a
    if t >= 1:
        return b
    return cv2.addWeighted(a, 1 - t, b, t, 0)


def brighten(img: np.ndarray, amount: float) -> np.ndarray:
    """amount 0..1 pushes towards white (a flash)."""
    if amount <= 0.01:
        return img
    white = np.full_like(img, 255)
    return cv2.addWeighted(img, 1 - amount, white, amount, 0)


# -------------------------------------------------------------- transitions
def t_cut(a, b, p, **_):
    return a if p < 0.5 else b


def t_dissolve(a, b, p, **_):
    return blend(a, b, ease_in_out(p))


def t_dip(a, b, p, **_):
    k = 1 - abs(2 * p - 1)  # 0 -> 1 (black at the beat) -> 0
    src = a if p < 0.5 else b
    return cv2.convertScaleAbs(src, alpha=1 - ease_in_out(k))


def t_blur(a, b, p, **_):
    k = 1 - abs(2 * p - 1)
    mix = blend(a, b, ease_in_out(p))
    r = int(1 + 30 * k) | 1
    if r < 3:
        return mix
    h, w = mix.shape[:2]
    small = cv2.resize(mix, (w // 4, h // 4), interpolation=cv2.INTER_AREA)
    small = cv2.GaussianBlur(small, (0, 0), r / 4)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)


def t_whip(a, b, p, direction: str = "left", **_):
    """Fast swipe with motion blur; both shots move as one strip."""
    h, w = a.shape[:2]
    q = ease_in_out(p)
    speed = 6 * q * (1 - q)  # bell curve, peak at the beat
    horizontal = direction in ("left", "right")
    span = w if horizontal else h
    off = int(round(q * span))
    if horizontal:
        strip = np.concatenate([a, b], axis=1) if direction == "left" else np.concatenate([b, a], axis=1)
        x = off if direction == "left" else span - off
        frame = strip[:, x:x + w]
    else:
        strip = np.concatenate([a, b], axis=0) if direction == "up" else np.concatenate([b, a], axis=0)
        y = off if direction == "up" else span - off
        frame = strip[y:y + h, :]
    return motion_blur(np.ascontiguousarray(frame), int(span * 0.12 * speed), horizontal)


def t_zoom_in(a, b, p, **_):
    """Punch through the outgoing shot into the next one."""
    if p < 0.5:
        q = ease_in(p * 2)
        return zoom_blur(a, 1 + 0.9 * q, 0.25 * q)
    q = ease_out((p - 0.5) * 2)
    return zoom_blur(b, 1.6 - 0.6 * q, 0.25 * (1 - q))


def t_zoom_out(a, b, p, **_):
    """Pull back out of the outgoing shot, the next one settles in from close up."""
    if p < 0.5:
        q = ease_in(p * 2)
        # shrinking frame; reflected borders read as a mirror tunnel, which looks intentional
        return zoom_blur(a, 1 / (1 + 0.8 * q), 0.15 * q)
    q = ease_out((p - 0.5) * 2)
    return zoom_blur(b, 1.8 - 0.8 * q, 0.2 * (1 - q))


def t_spin(a, b, p, clockwise: bool = True, **_):
    sign = -1 if clockwise else 1
    if p < 0.5:
        q = ease_in(p * 2)
        img, ang, sc = a, sign * 75 * q, 1 + 0.6 * q
    else:
        q = ease_out((p - 0.5) * 2)
        img, ang, sc = b, -sign * 75 * (1 - q), 1.6 - 0.6 * q
    # rotational blur: average three nearby angles
    spread = 6 * (1 - abs(2 * p - 1))
    h, w = img.shape[:2]
    small = cv2.resize(img, (w // 2, h // 2), interpolation=cv2.INTER_AREA)
    acc = np.zeros(small.shape, np.float32)
    for d in (-spread, 0, spread):
        acc += affine(small, sc, ang + d)
    return cv2.resize((acc / 3).astype(np.uint8), (w, h), interpolation=cv2.INTER_LINEAR)


def t_flash(a, b, p, **_):
    src = a if p < 0.5 else b
    k = 1 - abs(2 * p - 1)
    amount = 0.9 * (k ** 1.5) if p < 0.5 else 0.9 * (k ** 0.8)  # sharp rise, slower decay
    return brighten(src, amount)


def t_glitch(a, b, p, seed: int = 0, **_):
    src = a if p < 0.5 else b
    k = 1 - abs(2 * p - 1)
    if k < 0.05:
        return src
    h, w = src.shape[:2]
    out = src.copy()
    shift = int(40 * k)
    out[..., 0] = np.roll(src[..., 0], shift, axis=1)   # red right
    out[..., 2] = np.roll(src[..., 2], -shift, axis=1)  # blue left
    rng = np.random.default_rng(seed + int(p * 1000))
    for _ in range(int(3 + 8 * k)):  # displaced horizontal slices
        y = int(rng.integers(0, h - 20))
        hh = int(rng.integers(10, 80))
        dx = int(rng.integers(-1, 2) * rng.integers(20, 120) * k)
        out[y:y + hh] = np.roll(out[y:y + hh], dx, axis=1)
    return out


TRANSITIONS = {
    "cut": t_cut, "dissolve": t_dissolve, "fade": t_dissolve, "dip": t_dip, "blur": t_blur,
    "whip": t_whip, "zoom_in": t_zoom_in, "zoom_out": t_zoom_out, "spin": t_spin,
    "flash": t_flash, "glitch": t_glitch,
}

# old ffmpeg xfade names (plans made by earlier versions) -> closest new transition
LEGACY = {"fadeblack": "dip", "fadewhite": "flash", "slideleft": "whip", "slideright": "whip",
          "smoothleft": "whip", "smoothright": "whip", "wipeleft": "whip", "wiperight": "whip",
          "circleopen": "zoom_in", "zoomin": "zoom_in", "radial": "spin", "pixelize": "glitch",
          "distance": "blur", "hblur": "blur"}

# how long each transition likes to be (seconds); scaled by the style's duration setting
NATURAL = {"cut": 0.0, "dissolve": 0.5, "fade": 0.5, "dip": 0.5, "blur": 0.45, "whip": 0.3,
           "zoom_in": 0.36, "zoom_out": 0.4, "spin": 0.42, "flash": 0.24, "glitch": 0.2}


def normalize(name: str | None) -> str | None:
    if not name:
        return None
    n = str(name).lower()
    n = LEGACY.get(n, n)
    return n if n in TRANSITIONS and n != "cut" else None


def apply_transition(name: str, a: np.ndarray, b: np.ndarray, p: float, params: dict | None = None) -> np.ndarray:
    fn = TRANSITIONS.get(name, t_dissolve)
    return fn(a, b, _clip(p), **(params or {}))


# ---------------------------------------------------------- per-shot motion
def shot_motion(t_abs: float, seg: dict, beats: list[float], cfg: dict) -> tuple[float, float, float, float]:
    """(scale, angle, tx, ty) for one frame of a shot at output time t_abs.

    - punch: quick zoom bump on every beat inside the shot (energy dependent)
    - shake: decaying handheld-style shake on a drop
    - push: slow zoom on otherwise static video so nothing ever sits dead still
    """
    scale, angle, tx, ty = 1.0, 0.0, 0.0, 0.0
    start, dur = seg["out_start"], seg["dur"]
    local = t_abs - start
    level = seg.get("level", "medium")

    amp = float(cfg.get("beat_punch", 0.0) or 0.0)
    if amp > 0 and level in (cfg.get("punch_on") or ["medium", "intense"]):
        if level == "medium":
            amp *= 0.8
        tau = 0.13
        bump = 0.0
        half_frame = 0.5 / 30
        for b in beats:
            if b > t_abs + half_frame:  # beats sit a ms or two off the frame grid: snap them
                break
            d = max(0.0, t_abs - b)
            if d < 0.6 and b >= start - 0.02:
                bump = max(bump, math.exp(-d / tau))
        scale *= 1 + amp * bump

    # explicit per segment (effects.mark_shakes); plans from before that: only intense drops
    shake = seg.get("shake") if "shake" in seg else (cfg.get("shake_on_drop") and seg.get("drop")
                                                       and level == "intense")
    if shake:
        d = local
        if 0 <= d < 0.7:
            k = math.exp(-d / 0.18) * float(cfg.get("shake_px", 22))
            tx += k * math.sin(d * 71.0)
            ty += k * math.sin(d * 53.0 + 1.3)
            angle += 0.6 * math.exp(-d / 0.18) * math.sin(d * 37.0)
            scale *= 1.04  # hide borders while shaking

    push = float(cfg.get("video_push", 0.0) or 0.0)
    if push > 0 and seg.get("kind") == "video" and seg.get("static", False) and dur > 0:
        scale *= 1 + push * _clip(local / dur)
    return scale, angle, tx, ty


# ------------------------------------------------------------- pulse / bulge
_grid_cache: dict = {}


def bulge(img: np.ndarray, k: float) -> np.ndarray:
    """'Pop' distortion: magnify the centre of the frame by k (0..~0.25)."""
    if k < 0.005:
        return img
    h, w = img.shape[:2]
    key = (h, w)
    if key not in _grid_cache:
        ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
        cx, cy = w / 2, h / 2
        dx, dy = xs - cx, ys - cy
        r2 = (dx / (w * 0.62)) ** 2 + (dy / (h * 0.62)) ** 2
        _grid_cache[key] = (cx, cy, dx, dy, np.clip(1 - r2, 0, 1))
    cx, cy, dx, dy, fall = _grid_cache[key]
    f = 1 - k * fall
    return cv2.remap(img, cx + dx * f, cy + dy * f, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)


def pulse_amount(t_abs: float, seg: dict, beats: list[float], cfg: dict) -> float:
    amp = float(cfg.get("pulse", 0.0) or 0.0)
    if amp <= 0 or seg.get("level") not in (cfg.get("pulse_on") or ["intense"]):
        return 0.0
    best = 0.0
    for b in beats:
        if b > t_abs + 0.5 / 30:
            break
        d = max(0.0, t_abs - b)
        if d < 0.3:
            best = max(best, math.exp(-d / 0.07))
    return amp * best
