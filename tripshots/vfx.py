"""Video effects on one shot (segment `effect` {id, amount}), drawn frame by frame in render's compositor.

Each effect is our own small numpy/OpenCV function of (frame, t seconds into the shot, amount 0..1, beats as
seconds into the shot). They are meant to be used sparingly, where the shot asks for it: fxlib.py describes
each one (mood, energy, what it suits) for the effects director, which picks them.
"""
from __future__ import annotations

import cv2
import numpy as np


def _mix(a: np.ndarray, b: np.ndarray, k: float) -> np.ndarray:
    k = max(0.0, min(1.0, k))
    return a if k <= 0.001 else cv2.addWeighted(a, 1 - k, b, k, 0)


def _grain(h: int, w: int, t: float, amount: float) -> np.ndarray:
    rng = np.random.default_rng(int(t * 30) % 997)
    g = rng.normal(0, 1, (h // 3, w // 3)).astype(np.float32)
    return cv2.resize(g, (w, h), interpolation=cv2.INTER_LINEAR) * amount


def vhs(fr, t, a, beats):
    """An old camcorder: colour bleeding sideways, soft scan lines, a little noise, a jittery line now and then."""
    h, w = fr.shape[:2]
    small = cv2.resize(fr, (w // 3, h // 3), interpolation=cv2.INTER_AREA)
    soft = cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR).astype(np.float32)
    sh = int(6 * a) + 1
    soft[..., 0] = np.roll(soft[..., 0], sh, axis=1)
    soft[..., 2] = np.roll(soft[..., 2], -sh, axis=1)
    lines = (0.88 + 0.12 * (np.arange(h) % 4 < 2)).astype(np.float32)[:, None, None]
    out = soft * (1 - 0.6 * a + 0.6 * a * lines) + _grain(h, w, t, 10 * a)[..., None]
    rng = np.random.default_rng(int(t * 30))
    if rng.random() < 0.15 * a:  # a tracking glitch: a band slides sideways
        y = int(rng.integers(0, h - 40))
        out[y:y + 40] = np.roll(out[y:y + 40], int(rng.integers(-30, 30)), axis=1)
    out = out * np.array([1.03, 0.98, 1.04], np.float32)
    return np.clip(out, 0, 255).astype(np.uint8)


def dust(fr, t, a, beats):
    """Old film: grain, specks of dust, a hair-thin scratch, a slight flicker of the exposure."""
    h, w = fr.shape[:2]
    rng = np.random.default_rng(int(t * 24))
    out = fr.astype(np.float32) * (1 + 0.04 * a * rng.uniform(-1, 1)) + _grain(h, w, t, 14 * a)[..., None]
    for _ in range(int(6 * a)):
        x, y = int(rng.integers(0, w)), int(rng.integers(0, h))
        cv2.circle(out, (x, y), int(rng.integers(1, 4)), (30, 30, 30) if rng.random() < 0.6 else (230, 230, 220), -1)
    if rng.random() < 0.5 * a:
        x = int(rng.integers(0, w))
        cv2.line(out, (x, 0), (x + int(rng.integers(-20, 20)), h), (200, 200, 190), 1)
    warm = np.array([1.04, 1.0, 0.92], np.float32)
    return np.clip(out * (1 + (warm - 1) * a), 0, 255).astype(np.uint8)


def glow(fr, t, a, beats):
    """The highlights bloom softly (sunsets, city lights, water catching the sun)."""
    h, w = fr.shape[:2]
    small = cv2.resize(fr, (w // 4, h // 4), interpolation=cv2.INTER_AREA).astype(np.float32)
    bright = np.clip(small - 150, 0, 255) * 1.6
    bloom = cv2.GaussianBlur(bright, (0, 0), 12)
    bloom = cv2.resize(bloom, (w, h), interpolation=cv2.INTER_LINEAR)
    return np.clip(fr.astype(np.float32) + bloom * 0.8 * a, 0, 255).astype(np.uint8)


def dream(fr, t, a, beats):
    """Soft and hazy: a gentle diffusion, lifted shadows, warm edges that fall out of focus."""
    h, w = fr.shape[:2]
    small = cv2.resize(fr, (w // 4, h // 4), interpolation=cv2.INTER_AREA)
    blur = cv2.resize(cv2.GaussianBlur(small, (0, 0), 6), (w, h), interpolation=cv2.INTER_LINEAR)
    out = cv2.addWeighted(fr, 1 - 0.35 * a, blur, 0.35 * a, 0).astype(np.float32)
    out = out * (1 - 0.12 * a) + 30 * a
    yy, xx = np.ogrid[:h, :w]
    edge = np.clip((np.hypot((xx - w / 2) / (w / 2), (yy - h / 2) / (h / 2)) - 0.6) / 0.6, 0, 1)[..., None]
    out = out * (1 - edge * a) + blur.astype(np.float32) * edge * a
    return np.clip(out * np.array([1.04, 1.0, 0.95], np.float32), 0, 255).astype(np.uint8)


def mono(fr, t, a, beats):
    """Black and white with deep blacks: a moment taken out of time."""
    g = cv2.cvtColor(fr, cv2.COLOR_RGB2GRAY)
    g = cv2.convertScaleAbs(g, alpha=1.18, beta=-18)
    return _mix(fr, cv2.cvtColor(g, cv2.COLOR_GRAY2RGB), a)


def duotone(fr, t, a, beats, dark=(28, 22, 70), light=(255, 196, 120)):
    """Two colours only, shadows in one and light in the other (a poster look)."""
    g = cv2.cvtColor(fr, cv2.COLOR_RGB2GRAY).astype(np.float32)[..., None] / 255.0
    out = np.array(dark, np.float32) * (1 - g) + np.array(light, np.float32) * g
    return _mix(fr, out.astype(np.uint8), a)


def chroma(fr, t, a, beats):
    """The colour channels sit a little apart, more at the edges of the frame (a lens with character)."""
    sh = int(round(10 * a))
    if sh < 1:
        return fr
    out = fr.copy()
    out[..., 0] = np.roll(fr[..., 0], sh, axis=1)
    out[..., 2] = np.roll(fr[..., 2], -sh, axis=1)
    return out


def flicker(fr, t, a, beats):
    """The exposure jumps on each beat and settles (strobe-like, for an intense section)."""
    since = min([t - b for b in beats if b <= t] or [9.0])
    k = a * np.exp(-since * 12)
    return cv2.convertScaleAbs(fr, alpha=1 + 0.6 * k, beta=25 * k) if k > 0.02 else fr


def mirror(fr, t, a, beats):
    """The left half reflected onto the right: a symmetric, graphic frame."""
    w = fr.shape[1]
    out = fr.copy()
    out[:, w - w // 2:] = fr[:, :w // 2][:, ::-1]
    return _mix(fr, out, 1.0 if a >= 0.5 else a * 2)


def handheld(fr, t, a, beats):
    """A slow, breathing handheld drift on a locked-off shot (makes a tripod shot feel lived-in)."""
    from .motion import affine
    h, w = fr.shape[:2]
    dx = (np.sin(t * 1.3) + 0.5 * np.sin(t * 2.9 + 1)) * 0.006 * w * a
    dy = (np.sin(t * 1.1 + 2) + 0.5 * np.sin(t * 3.3)) * 0.006 * h * a
    return affine(fr, 1.03, float(np.sin(t * 0.9) * 0.4 * a), float(dx), float(dy))


def leak(fr, t, a, beats):
    """A warm light leak drifting across the frame (film, memories, golden hour)."""
    h, w = fr.shape[:2]
    yy, xx = np.ogrid[:h, :w]
    cx = w * (0.1 + 0.8 * ((t * 0.18) % 1.0))
    d = np.exp(-(((xx - cx) / (0.45 * w)) ** 2 + ((yy - 0.3 * h) / (0.7 * h)) ** 2)).astype(np.float32)[..., None]
    col = np.array([255, 140, 60], np.float32)
    return np.clip(fr.astype(np.float32) + d * col * 0.55 * a, 0, 255).astype(np.uint8)


def tiltshift(fr, t, a, beats):
    """A sharp band through the middle and blur above and below: the scene looks like a miniature model."""
    h, w = fr.shape[:2]
    small = cv2.resize(fr, (w // 4, h // 4), interpolation=cv2.INTER_AREA)
    blur = cv2.resize(cv2.GaussianBlur(small, (0, 0), 5), (w, h), interpolation=cv2.INTER_LINEAR)
    m = np.clip((np.abs(np.arange(h) / h - 0.55) - 0.12) / 0.2, 0, 1).astype(np.float32)[:, None, None] * a
    out = fr.astype(np.float32) * (1 - m) + blur.astype(np.float32) * m
    hsv = cv2.cvtColor(np.clip(out, 0, 255).astype(np.uint8), cv2.COLOR_RGB2HSV)
    hsv[..., 1] = np.clip(hsv[..., 1] * (1 + 0.3 * a), 0, 255).astype(np.uint8)
    return cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB)


EFFECTS = {"vhs": vhs, "dust": dust, "glow": glow, "dream": dream, "mono": mono, "duotone": duotone,
           "chroma": chroma, "flicker": flicker, "mirror": mirror, "handheld": handheld, "leak": leak,
           "tiltshift": tiltshift}


def apply(fr: np.ndarray, effect: dict | str | None, t: float, beats: list[float] | None = None) -> np.ndarray:
    """One shot's effect on one frame (t = seconds into the shot, beats = seconds into the shot)."""
    if not effect:
        return fr
    if isinstance(effect, str):
        effect = {"id": effect}
    fn = EFFECTS.get(str(effect.get("id")))
    if not fn:
        return fr
    a = max(0.0, min(1.0, float(effect.get("amount", 0.6))))
    return fn(np.ascontiguousarray(fr), float(t), a, beats or [])
