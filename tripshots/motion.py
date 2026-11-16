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


_leak_cache: dict = {}


def t_leak(a, b, p, warmth: float = 1.0, **_):
    """Film light leak: warm, soft light washes across the frame (screen blend) while the shots dissolve
    under it, brightest at the cut. After the organic light-leak overlay in the HyperFrames registry."""
    h, w = a.shape[:2]
    k = 1 - abs(2 * p - 1)  # 0 -> 1 at the cut -> 0
    key = (h, w)
    if key not in _leak_cache:  # one field per frame size, at low resolution
        sh, sw = max(8, h // 8), max(8, w // 8)
        yy, xx = np.mgrid[0:sh, 0:sw].astype(np.float32)
        _leak_cache[key] = (xx / sw, yy / sh, (sh, sw))
    xx, yy, (sh, sw) = _leak_cache[key]
    c = -0.35 + 1.7 * ease_in_out(p)  # the bands drift across, leaning like light through a lens gap
    d1 = (xx + 0.35 * yy) - c
    d2 = (xx * 0.8 - 0.25 * yy) - (c - 0.28)
    band = np.exp(-(d1 / 0.2) ** 2) + 0.6 * np.exp(-(d2 / 0.12) ** 2)
    glow = np.exp(-((xx - c) ** 2 + (yy - 0.25) ** 2) / 0.18) * 0.7
    inten = np.clip((band + glow) * (0.2 + 0.75 * k), 0, 1.0)
    col = np.stack([0.20 + 0.15 * (1 - yy), 0.55 + 0.15 * yy, np.full_like(yy, 1.0)], -1)  # BGR: amber -> rose
    col[..., 0] *= 1.0 / max(0.5, warmth)
    light = cv2.resize((inten[..., None] * col).astype(np.float32), (w, h), interpolation=cv2.INTER_LINEAR)
    base = blend(a, b, ease_in_out(p)).astype(np.float32) / 255.0
    out = 1 - (1 - base) * (1 - np.clip(light, 0, 1))  # screen
    return (np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8)


# ---------------------------------------------------- masked reveals (keyframed on the beat)
# The next shot comes in through a shape: a line that swings round a corner, a V that opens from the bottom edge,
# a circle that grows from the middle. The line and the V move in steps that snap on each beat inside the
# transition and hold in between (an editor's keyframes on the beat markers), with a thin white edge along the cut
# of the mask; the circle grows smoothly with a soft edge, a ripple running round it and a glow as it opens.
# After a CapCut masking-transition tutorial (linear, split and circle masks with beat keyframes).
_grid_masks: dict = {}
MASKS = ("split", "vsplit", "iris", "slats", "stripes", "diamond", "frame", "cells")


def _geo(key, make):
    """Per-pixel geometry (distances, angles) for a frame size and shape, computed once."""
    if key not in _grid_masks:
        if len(_grid_masks) > 24:
            _grid_masks.clear()
        _grid_masks[key] = make()
    return _grid_masks[key]


def _xy(h: int, w: int):
    return _geo(("xy", h, w), lambda: tuple(np.mgrid[0:h, 0:w].astype(np.float32)[::-1]))


def _stepped(p: float, steps: int) -> float:
    """0..1 in `steps` moves, each a quick ease-out right after its beat, then a hold."""
    steps = max(1, int(steps))
    k = min(steps - 1, int(p * steps))
    u = p * steps - k
    return (k + ease_out(min(1.0, u / 0.4))) / steps


def _reveal(a, b, d: np.ndarray, edge: float) -> np.ndarray:
    """b where the signed distance d (px) > 0, a elsewhere, anti-aliased, with a thin white line along d = 0."""
    m = np.clip(0.5 + d * (1 / 1.5), 0.0, 1.0)
    out = cv2.blendLinear(b, a, m, 1.0 - m)
    if edge > 0:
        lw = max(2.0, a.shape[1] / 360.0)
        e = np.clip(1.0 + lw / 2 - np.abs(d), 0.0, 1.0) * (0.9 * edge)
        if float(e.max()) > 0:
            out = cv2.blendLinear(np.full_like(out, 255), out, e, 1.0 - e)
    return out


def t_split(a, b, p, pivot: str = "bl", steps: int = 2, **_):
    """A line swings round a corner of the frame, 45° on each beat, opening the next shot behind it."""
    h, w = a.shape[:2]

    def make():
        xx, yy = _xy(h, w)
        dx = xx if pivot[1:] == "l" else (w - xx)
        dy = (h - yy) if pivot[0] == "b" else yy
        return np.hypot(dx, dy), np.arctan2(dy, dx)  # 0 along the bottom (top) edge -> 90° up the side
    r, phi = _geo(("split", h, w, pivot), make)
    theta = np.float32(np.radians(92.0) * _stepped(p, steps))
    return _reveal(a, b, r * np.sin(theta - phi), 1.0 if 0.0 < p < 0.999 else 0.0)


def t_vsplit(a, b, p, side: str = "bottom", steps: int = 2, **_):
    """A V opens from the middle of the bottom (or top) edge, 45° each side on each beat."""
    h, w = a.shape[:2]

    def make():
        xx, yy = _xy(h, w)
        dx, dy = xx - w / 2, ((h - yy) if side == "bottom" else yy)
        return np.hypot(dx, dy), np.abs(np.arctan2(dx, dy))  # angle from straight up (down)
    r, psi = _geo(("vsplit", h, w, side), make)
    alpha = np.float32(np.radians(92.0) * _stepped(p, steps))
    return _reveal(a, b, r * np.sin(np.clip(alpha - psi, -1.5, 1.5)), 1.0 if 0.0 < p < 0.999 else 0.0)


def t_iris(a, b, p, cx: float = 0.5, cy: float = 0.5, **_):
    """The next shot in a circle that grows from a point to the whole frame: a soft edge, a ripple running
    round the rim, and a glow in the middle as it opens."""
    h, w = a.shape[:2]
    ox, oy = cx * w, cy * h

    def make():
        xx, yy = _xy(h, w)
        dist = np.hypot(xx - ox, yy - oy)
        return dist, (xx - ox) / np.maximum(dist, 1.0), (yy - oy) / np.maximum(dist, 1.0)
    dist, ux, uy = _geo(("iris", h, w, round(cx, 3), round(cy, 3)), make)
    far = float(max(np.hypot(ox, oy), np.hypot(w - ox, oy), np.hypot(ox, h - oy), np.hypot(w - ox, h - oy)))
    q = 0.55 * p + 0.45 * ease_in_out(p)  # opens steadily: the circle is seen growing, not just at the end
    s = float(min(w, h))
    feather = 0.08 * s
    rad = 0.02 * s + q * (far + feather)
    m = np.clip((rad - dist) * (1 / feather) + 0.5, 0.0, 1.0)
    band = np.exp(-((dist - rad) * (1 / (0.07 * s))) ** 2)
    amp = 0.012 * s * (1 - q)
    if amp > 0.5:  # the ripple: near the rim the picture is pushed in and out along the radius, travelling out
        xx, yy = _xy(h, w)
        wave = np.sin((dist - rad) * (2 * np.pi / (0.025 * s)) - p * 12) * band * amp
        b = cv2.remap(b, xx + ux * wave, yy + uy * wave, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    out = cv2.blendLinear(b, a, m, 1.0 - m)
    glow = 0.65 * (1 - q) ** 2 * np.exp(-(dist * (1 / max(rad * 0.9, 1.0))) ** 2) * m + 0.25 * (1 - q) * band
    if float(glow.max()) > 0.01:  # a bright core while it opens, a light rim (screen blend)
        g = np.clip(glow, 0, 1)
        out = (255 - (255 - out.astype(np.float32)) * (1 - g[..., None]) + 0.5).astype(np.uint8)
    return out


# ---------------------------------------------------- paper shapes
# The next shot is built from pieces: slats across the frame, stripes down it, or a diamond from the middle. Each
# piece comes in as a plain paper-coloured block first, then the picture shows through it (a graphic, editorial
# shape-cut). Pieces follow each other in a steady stagger; thin paper seams show between them while it builds.
PAPER = (242, 238, 228)


def _pieces(a, b, idx: np.ndarray, along: np.ndarray, n: int, p: float, seams: np.ndarray | None) -> np.ndarray:
    """idx: which piece each pixel belongs to (0..n-1, in the order they come in); along: 0..1 where in its piece
    the pixel sits (the block fills along it)."""
    span = 0.45
    start = np.linspace(0.0, 1.0 - span, n).astype(np.float32)
    q = np.clip((p - start) / span, 0.0, 1.0)[idx]                      # each piece's own progress
    fill = np.clip(q / 0.4, 0.0, 1.0)                                   # 0-40 %: the paper block slides in
    show = np.clip((q - 0.4) / 0.35, 0.0, 1.0)                          # 40-75 %: the picture shows through it
    paper_on = (along <= fill).astype(np.float32) * (1.0 - show)
    out = cv2.blendLinear(b, a, show * (along <= fill), 1.0 - show * (along <= fill))
    if float(paper_on.max()) > 0:
        out = cv2.blendLinear(np.full_like(a, PAPER), out, paper_on, 1.0 - paper_on)
    if seams is not None and 0.0 < p < 0.98:
        e = seams * (0.85 * max(0.0, min(1.0, (0.92 - p) / 0.2)))  # gone before the shot settles
        out = cv2.blendLinear(np.full_like(a, PAPER), out, e, 1.0 - e)
    return out


def t_slats(a, b, p, n: int = 6, **_):
    """Upright slats, left to right: each a paper block dropping in, then the next shot through it."""
    h, w = a.shape[:2]

    def make():
        xx, yy = _xy(h, w)
        idx = np.minimum((xx * n / w).astype(np.int32), n - 1)
        lw = max(2.0, w / 480)
        seam = (np.abs((xx * n / w) - np.round(xx * n / w)) * (w / n) < lw / 2).astype(np.float32)
        return idx, yy / h, seam
    idx, along, seam = _geo(("slats", h, w, n), make)
    return _pieces(a, b, idx, along, n, p, seam)


def t_stripes(a, b, p, n: int = 7, **_):
    """Stripes across the frame, top to bottom: each a paper bar sliding in, then the next shot through it."""
    h, w = a.shape[:2]

    def make():
        xx, yy = _xy(h, w)
        idx = np.minimum((yy * n / h).astype(np.int32), n - 1)
        lw = max(2.0, h / 480)
        seam = (np.abs((yy * n / h) - np.round(yy * n / h)) * (h / n) < lw / 2).astype(np.float32)
        return idx, xx / w, seam
    idx, along, seam = _geo(("stripes", h, w, n), make)
    return _pieces(a, b, idx, along, n, p, seam)


def t_diamond(a, b, p, **_):
    """A diamond from the middle, then the corners: the centre piece, then the four triangles round it (an X of
    paper seams between them), each a paper block first."""
    h, w = a.shape[:2]

    def make():
        xx, yy = _xy(h, w)
        u, v = np.abs(xx - w / 2) / (w / 2), np.abs(yy - h / 2) / (h / 2)
        r = u + v                                                       # 1 = the diamond's edge
        inner = r <= 1.0
        quad = (xx >= w / 2).astype(np.int32) + 2 * (yy >= h / 2).astype(np.int32)
        idx = np.where(inner, 0, 1 + quad).astype(np.int32)             # 0 the diamond, 1-4 the corners
        along = np.where(inner, r, (r - 1.0)).astype(np.float32)        # the diamond fills outwards
        lw = max(2.0, min(w, h) / 360) / (min(w, h) / 2)
        seam = ((np.abs(r - 1.0) < lw) | (np.abs(u - v) * (r > 1.0) < lw * 0.5) & (r > 1.0)).astype(np.float32)
        return idx, np.clip(along, 0, 1), seam
    idx, along, seam = _geo(("diamond", h, w), make)
    return _pieces(a, b, idx, along, 5, p, seam)


def t_frame(a, b, p, **_):
    """The next shot as a window in the middle first, then panels round it (left, bottom, top, right), each a paper
    block before the picture shows through. Thin gaps between the panels still show the old shot, like lines
    framing the window, until it all snaps into the whole picture at the end."""
    h, w = a.shape[:2]

    def make():
        xx, yy = _xy(h, w)
        u, v = xx / w, yy / h
        g = 0.012
        x0, x1, y0, y1 = 0.15, 0.85, 0.26, 0.74
        cen = (u >= x0) & (u < x1) & (v >= y0) & (v < y1)
        left, right = u < x0 - g, u >= x1 + g
        mid = (u >= x0) & (u < x1)
        top, bot = mid & (v < y0 - g), mid & (v >= y1 + g * w / h)
        idx = np.full((h, w), -1, np.int32)
        for k, m in enumerate((cen, left, bot, top, right)):
            idx[m] = k
        along = np.select([cen, left, bot, top, right],
                          [(u - x0) / (x1 - x0), v, (u - x0) / (x1 - x0), 1.0 - (u - x0) / (x1 - x0), 1.0 - v], 0.0)
        return np.maximum(idx, 0), np.clip(along, 0, 1).astype(np.float32), (idx < 0)
    idx, along, gaps = _geo(("frame", h, w), make)
    out = _pieces(a, b, idx, along, 5, min(1.0, p / 0.8), None)  # built by 80 %, held, then whole
    if p < 0.97:
        out[gaps] = a[gaps]
    return out


# ---------------------------------------------------- the grid
# A fine grid of light lines over the reel; the next shot fills in cell by cell, spreading from one spot (a cell
# shows as a flat block of its colour for a moment first), and a photo wall: the cells round the subject fill with
# little pictures from the rest of the trip, hold, and clear again. After the grid-mosaic trend.
def grid_shape(w: int, h: int, cols: int) -> tuple[int, int]:
    """(cols, rows) of nearly square cells."""
    return cols, max(1, int(round(cols * h / w)))


def _cells(h: int, w: int, cols: int):
    def make():
        c, r = grid_shape(w, h, cols)
        xx, yy = _xy(h, w)
        ci = np.minimum((xx * c / w).astype(np.int32), c - 1)
        ri = np.minimum((yy * r / h).astype(np.int32), r - 1)
        return c, r, ri * c + ci
    return _geo(("cells", h, w, cols), make)


def cell_order(c: int, r: int, ox: float, oy: float, seed: int, jitter: float = 0.12) -> np.ndarray:
    """0..1 per cell: when it turns, spreading out from the cell at (ox, oy) with some randomness."""
    gx, gy = np.meshgrid((np.arange(c) + 0.5) / c, (np.arange(r) + 0.5) / r)
    d = np.hypot((gx - ox) * c, (gy - oy) * r).ravel()
    d = d / max(float(d.max()), 1e-6)
    d = d + jitter * np.random.default_rng(seed).random(c * r)
    rank = np.argsort(np.argsort(d))
    return (rank / max(1, c * r - 1)).astype(np.float32)


def t_cells(a, b, p, cols: int = 8, seed: int = 0, ox: float = 0.5, oy: float = 0.5, **_):
    """The next shot fills in cell by cell from one spot; each cell is a flat block of its colour for a moment."""
    h, w = a.shape[:2]
    c, r, idx = _cells(h, w, cols)
    order = cell_order(c, r, ox, oy, seed)
    q = np.clip((p - order * 0.75) / 0.25, 0.0, 1.0)              # each cell's own turn
    means = cv2.resize(b, (c, r), interpolation=cv2.INTER_AREA).reshape(-1, 3).astype(np.float32)
    pastel = (means * 0.55 + 255 * 0.45)                           # a soft block of the cell's colour
    blocks = pastel[idx].astype(np.uint8)
    # about a third of the cells show their colour block for a moment on the way; the rest turn straight over
    blocky = (np.random.default_rng(seed + 7).random(c * r) < 0.35)[idx]
    state = q[idx]
    out = a.copy()
    sel_block = (state > 0) & (state < 0.6) & blocky
    sel_pic = (state >= 0.6) | ((state > 0.15) & ~blocky)
    out[sel_block] = blocks[sel_block]
    out[sel_pic] = b[sel_pic]
    return out


def grid_lines(h: int, w: int, cols: int) -> np.ndarray:
    """0..1 mask of the grid's thin lines."""
    def make():
        c, r = grid_shape(w, h, cols)
        m = np.zeros((h, w), np.float32)
        lw = max(2, int(round(w / 540)))
        for k in range(1, c):
            x = int(round(k * w / c))
            m[:, max(0, x - lw // 2):x - lw // 2 + lw] = 1.0
        for k in range(1, r):
            y = int(round(k * h / r))
            m[max(0, y - lw // 2):y - lw // 2 + lw, :] = 1.0
        return m
    return _geo(("gridlines", h, w, cols), make)


def grid_overlay(frame: np.ndarray, cols: int, alpha: float = 0.3) -> np.ndarray:
    m = grid_lines(frame.shape[0], frame.shape[1], cols) * float(alpha)
    return cv2.blendLinear(np.full_like(frame, 245), frame, m, 1.0 - m)


def mosaic(frame: np.ndarray, tiles: dict, cols: int, u: float, seed: int = 0) -> np.ndarray:
    """The photo wall at u (0..1 through its shot): tiles {cell index: picture at cell size} fill in one by one
    from the subject outwards over the first half, hold, and clear again in the last fifth."""
    if not tiles:
        return frame
    h, w = frame.shape[:2]
    c, r = grid_shape(w, h, cols)
    keys = sorted(tiles)
    np.random.default_rng(seed).shuffle(keys)
    turn = dict(zip(keys, np.linspace(0.05, 0.5, len(keys))))
    out = frame
    for k in keys:
        on, off = turn[k], 0.8 + 0.15 * turn[k] / 0.5
        if not on <= u < off:
            continue
        if out is frame:
            out = frame.copy()
        ci, ri = k % c, k // c
        x0, x1 = int(round(ci * w / c)), int(round((ci + 1) * w / c))
        y0, y1 = int(round(ri * h / r)), int(round((ri + 1) * h / r))
        t = tiles[k]
        if u < on + 0.03:  # a flat block of its colour for a frame or two first
            out[y0:y1, x0:x1] = (t.reshape(-1, 3).mean(0) * 0.55 + 255 * 0.45).astype(np.uint8)
        else:
            out[y0:y1, x0:x1] = cv2.resize(t, (x1 - x0, y1 - y0))
    return out


def silhouette(frame: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """The people in the shot filled with paper colour for a moment (mask 0..1 at the frame's size)."""
    m = np.clip(mask, 0, 1).astype(np.float32)
    return cv2.blendLinear(np.full_like(frame, PAPER), frame, m, 1.0 - m)


def colour_in(frame: np.ndarray, k: float) -> np.ndarray:
    """The shot from black and white (k = 0) to its full colour (k = 1): a new shot arrives grey, then blooms."""
    if k >= 0.999:
        return frame
    g = cv2.cvtColor(cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY), cv2.COLOR_GRAY2RGB)
    w = np.full(frame.shape[:2], float(max(0.0, k)), np.float32)
    return cv2.blendLinear(frame, g, w, 1.0 - w)


TRANSITIONS = {
    "slats": t_slats, "stripes": t_stripes, "diamond": t_diamond, "frame": t_frame, "cells": t_cells,
    "split": t_split, "vsplit": t_vsplit, "iris": t_iris,
    "leak": t_leak,
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
           "zoom_in": 0.36, "zoom_out": 0.4, "spin": 0.42, "flash": 0.24, "glitch": 0.2, "leak": 0.7,
           "split": 0.9, "vsplit": 0.9, "iris": 0.8, "slats": 0.8, "stripes": 0.8, "diamond": 0.8, "frame": 1.0, "cells": 1.0}


def normalize(name: str | None) -> str | None:
    if not name:
        return None
    n = str(name).lower()
    n = LEGACY.get(n, n)
    return n if n in TRANSITIONS and n != "cut" else None


def apply_transition(name: str, a: np.ndarray, b: np.ndarray, p: float, params: dict | None = None) -> np.ndarray:
    fn = TRANSITIONS.get(name, t_dissolve)
    return fn(a, b, _clip(p), **(params or {}))


# ---------------------------------------------------------- easing
# How a move speeds up and settles, as editors name it (the GSAP family names). `ease(name, u)` is the share of
# the move done at u (0..1) of its time; learn measures which one a reference's camera moves follow (fit_ease).
EASES = {
    "linear": lambda u: u,
    "sine": lambda u: 0.5 - 0.5 * math.cos(math.pi * u),                 # gentle in and out (the default)
    "in": lambda u: u * u,                                              # gathers speed: leaves on the move
    "out": lambda u: 1 - (1 - u) ** 2,                                  # starts on the move, settles
    "expo_out": lambda u: (1 - 2 ** (-8 * u)) / (1 - 2 ** -8),          # a snap that glides to rest
    "power3": lambda u: 4 * u ** 3 if u < 0.5 else 1 - (-2 * u + 2) ** 3 / 2,  # a firm push, held at both ends
}
# the same curves as ffmpeg expressions of x (0..1), for moves ffmpeg draws itself (pans)
EASE_EXPR = {
    "linear": "({x})", "sine": "(0.5-0.5*cos(PI*{x}))", "in": "(({x})*({x}))", "out": "(1-(1-{x})*(1-{x}))",
    "expo_out": "((1-pow(2\\,-8*{x}))/(1-pow(2\\,-8)))",
    "power3": "if(lt({x}\\,0.5)\\,4*pow({x}\\,3)\\,1-pow(-2*{x}+2\\,3)/2)",
}


def ease(name: str | None, u: float) -> float:
    u = max(0.0, min(1.0, u))
    return EASES.get(name or "sine", EASES["sine"])(u)


def fit_ease(progress) -> tuple[str, float] | None:
    """The named curve closest to a measured move: `progress` = share of the move done at evenly spaced times
    (0 -> 1). Returns (name, rms error), or None when the move is too short or not one move (back and forth)."""
    import numpy as np
    p = np.asarray(progress, float)
    if len(p) < 5 or np.any(np.diff(p) < -0.08):
        return None
    u = np.linspace(0, 1, len(p))
    errs = {k: float(np.sqrt(np.mean((p - np.array([f(x) for x in u])) ** 2))) for k, f in EASES.items()}
    best = min(errs, key=errs.get)
    return best, round(errs[best], 3)


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
    if amp > 0 and level in (cfg.get("punch_on") or ["medium", "intense"]) and not seg.get("breath") \
            and not seg.get("beatless"):  # the breath before a climax and beatless music don't pulse
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

    # hook punch: the opening shot starts pushed in and settles within 0.45 s, so something moves on the
    # very first frames even when the shot itself is calm (the scroll decision takes about 1.4 s)
    if cfg.get("hook_punch") and seg.get("role") == "hook" and not seg.get("hold") and start < 0.05 and local < 0.45:
        q = _clip(local / 0.45)
        scale *= 1 + 0.12 * (1 - q) ** 3

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
