"""Foreground masks for 'text behind the subject'.

Sky segmentation, no ML: sky is the smooth, sky-coloured region connected to the top of the
frame. Everything else (mountains, trees, buildings, a lighthouse, a person against the
sky) is foreground and gets composited back over the text, so a title can sit behind
the peaks.

Returns a float32 mask 0..1 (1 = foreground, in front of text) at frame resolution,
or None when the frame has no usable sky (then the caller falls back to normal text).
"""
from __future__ import annotations

import cv2
import numpy as np

WORK_W = 270  # analysis width (frame is 1080 wide): fast and plenty for a soft matte


def _sky_candidates(small: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    lab = cv2.cvtColor(small, cv2.COLOR_RGB2LAB).astype(np.float32)
    gray = lab[..., 0]
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    grad = cv2.GaussianBlur(np.hypot(gx, gy), (0, 0), 1.2)
    h = small.shape[0]
    # sky colour model from the top band (allowing a vertical gradient: fit per row band)
    top = lab[: max(4, h // 12)].reshape(-1, 3)
    ref = np.median(top, axis=0)
    spread = np.maximum(np.percentile(np.abs(top - ref), 90, axis=0), [6, 4, 4])
    # sky brightens/changes hue towards the horizon: compare each row with the row above's sky
    dist = np.abs(lab - ref) / (spread * 3.5 + np.array([25, 10, 10]))
    colour_ok = dist.max(axis=2) < 1.0
    smooth = grad < np.percentile(grad, 60) + 6
    return smooth, colour_ok


def sky_mask(frame: np.ndarray) -> np.ndarray | None:
    H, W = frame.shape[:2]
    sh = int(WORK_W * H / W)
    small = cv2.resize(frame, (WORK_W, sh), interpolation=cv2.INTER_AREA)
    smooth, colour_ok = _sky_candidates(small)
    lab = cv2.cvtColor(small, cv2.COLOR_RGB2LAB).astype(np.float32)

    # grow the sky downward row by row: a pixel is sky if it's smooth and close in colour to
    # the sky just above it (handles the blue -> orange sunset gradient), or matches the top model
    sky = np.zeros((sh, WORK_W), bool)
    sky[0] = smooth[0] | colour_ok[0]
    row_ref = lab[0].copy()
    for y in range(1, sh):
        prev = sky[y - 1]
        # dilate previous row's sky horizontally so it can flow around small gaps
        prev_d = cv2.dilate(prev.astype(np.uint8)[None], np.ones((1, 5), np.uint8))[0].astype(bool)
        d = np.abs(lab[y] - row_ref).max(axis=1)
        cand = smooth[y] & ((d < 9.0) | colour_ok[y])
        sky[y] = cand & prev_d
        upd = sky[y]
        row_ref[upd] = 0.7 * row_ref[upd] + 0.3 * lab[y][upd]
        # carry the reference sideways so neighbours of sky pixels have a reference too
        if upd.any():
            idx = np.where(upd)[0]
            fill = np.interp(np.arange(WORK_W), idx, np.arange(len(idx)))
            row_ref = np.where(upd[:, None], row_ref, row_ref[idx[np.clip(fill.round().astype(int), 0, len(idx) - 1)]])

    # clean up: fill small holes (stars, birds, wisps) and remove specks
    sky_u8 = sky.astype(np.uint8)
    sky_u8 = cv2.morphologyEx(sky_u8, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    sky_u8 = cv2.morphologyEx(sky_u8, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, lbl, stats, _ = cv2.connectedComponentsWithStats(sky_u8, 4)
    keep = np.zeros_like(sky_u8)
    for i in range(1, n):  # only sky regions touching the top edge
        x, y, w, h, area = stats[i]
        if y == 0 and area > 0.01 * sh * WORK_W:
            keep[lbl == i] = 1
    frac = keep.mean()
    top_frac = keep[: max(2, sh // 10)].mean()
    if frac < 0.08 or frac > 0.9 or top_frac < 0.6:
        return None
    fg = 1.0 - keep.astype(np.float32)
    fg = cv2.GaussianBlur(fg, (0, 0), 0.8)  # soft edge at analysis scale
    return cv2.resize(fg, (W, H), interpolation=cv2.INTER_LINEAR)


def skyline(fg: np.ndarray) -> np.ndarray:
    """Per column, the first row (from the top) that is foreground."""
    hit = fg > 0.5
    first = np.where(hit.any(axis=0), hit.argmax(axis=0), fg.shape[0])
    return first.astype(np.float32)


class MaskTracker:
    """Per-frame sky masks with light temporal smoothing (no flicker on moving shots)."""

    def __init__(self, alpha: float = 0.6):
        self.prev = None
        self.alpha = alpha
        self.misses = 0

    def __call__(self, frame: np.ndarray) -> np.ndarray | None:
        m = sky_mask(frame)
        if m is None:
            self.misses += 1
            return self.prev if self.misses < 4 else None
        self.misses = 0
        if self.prev is not None and self.prev.shape == m.shape:
            m = self.alpha * m + (1 - self.alpha) * self.prev
        self.prev = m
        return m
