"""Where is the subject, and how should a landscape frame be cut to 9:16 around it?

Sources of truth, best first:
  1. the AI's subject box (asked for when it judges the shot)
  2. on-device saliency (spectral residual): finds the detailed, eye-catching part of a frame
The result is a normalised box {x0, y0, x1, y1, cx, cy} in source-image coordinates.
"""
from __future__ import annotations

import subprocess

import cv2
import numpy as np

from .config import OUT_H, OUT_W
from .fx import hdr_chain
from .util import ffmpeg_base


def saliency_map(rgb: np.ndarray, width: int = 96) -> np.ndarray:
    """Spectral-residual saliency (Hou & Zhang 2007) plus a little colour contrast, 0..1."""
    h, w = rgb.shape[:2]
    sh = max(8, int(width * h / w))
    small = cv2.resize(rgb, (width, sh), interpolation=cv2.INTER_AREA).astype(np.float32)
    gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
    F = np.fft.fft2(gray)
    logA = np.log(np.abs(F) + 1e-6)
    resid = logA - cv2.blur(logA, (3, 3))
    S = np.abs(np.fft.ifft2(np.exp(resid + 1j * np.angle(F)))) ** 2
    S = cv2.GaussianBlur(S.astype(np.float32), (0, 0), 2.0)
    lab = cv2.cvtColor(small / 255.0, cv2.COLOR_RGB2LAB)
    col = np.linalg.norm(lab - lab.reshape(-1, 3).mean(0), axis=2)
    col = cv2.GaussianBlur(col.astype(np.float32), (0, 0), 3.0)

    def norm(a):
        lo, hi = np.percentile(a, 2), np.percentile(a, 99.5)
        return np.clip((a - lo) / (hi - lo + 1e-9), 0, 1)
    sal = 0.65 * norm(S) + 0.35 * norm(col)
    # mild centre bias: photographers usually put the subject near the middle
    yy, xx = np.mgrid[0:sh, 0:width]
    bias = np.exp(-(((xx / width - 0.5) / 0.55) ** 2 + ((yy / sh - 0.5) / 0.6) ** 2))
    return (sal * (0.75 + 0.25 * bias)).astype(np.float32)


def box_from_map(sal: np.ndarray, mass: float = 0.7) -> dict:
    """Box holding `mass` of the saliency, from the marginals (robust to speckle)."""
    h, w = sal.shape
    s = np.maximum(sal - np.percentile(sal, 55), 0)
    if s.sum() < 1e-6:
        return make_box(0.3, 0.3, 0.7, 0.7)
    lo, hi = (1 - mass) / 2, 1 - (1 - mass) / 2
    cx_m = np.cumsum(s.sum(0)) / s.sum()
    cy_m = np.cumsum(s.sum(1)) / s.sum()
    x0, x1 = np.searchsorted(cx_m, lo) / w, np.searchsorted(cx_m, hi) / w
    y0, y1 = np.searchsorted(cy_m, lo) / h, np.searchsorted(cy_m, hi) / h
    ys, xs = np.mgrid[0:h, 0:w]
    cx = float((s * xs).sum() / s.sum() / w)
    cy = float((s * ys).sum() / s.sum() / h)
    b = make_box(x0, y0, x1 + 1 / w, y1 + 1 / h)
    b["cx"], b["cy"] = cx, cy
    return b


def make_box(x0, y0, x1, y1) -> dict:
    x0, x1 = sorted((float(np.clip(x0, 0, 1)), float(np.clip(x1, 0, 1))))
    y0, y1 = sorted((float(np.clip(y0, 0, 1)), float(np.clip(y1, 0, 1))))
    if x1 - x0 < 0.02:
        x0, x1 = max(0, x0 - 0.05), min(1, x1 + 0.05)
    if y1 - y0 < 0.02:
        y0, y1 = max(0, y0 - 0.05), min(1, y1 + 0.05)
    return {"x0": round(x0, 4), "y0": round(y0, 4), "x1": round(x1, 4), "y1": round(y1, 4),
            "cx": round((x0 + x1) / 2, 4), "cy": round((y0 + y1) / 2, 4)}


def subject_for(shot: dict) -> dict:
    """Best subject box for a shot: AI box if we have one, else saliency of its thumbnail."""
    ai = shot.get("ai") or {}
    b = ai.get("subject_box")
    if isinstance(b, (list, tuple)) and len(b) == 4:
        try:
            box = make_box(*[float(v) for v in b])
            box["source"] = "ai"
            return box
        except (TypeError, ValueError):
            pass
    img = cv2.imread(shot.get("thumb", ""))
    if img is None:
        sx = float(ai.get("subject_x", 0.5))
        box = make_box(sx - 0.15, 0.3, sx + 0.15, 0.7)
        box["source"] = "default"
        return box
    box = box_from_map(saliency_map(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)))
    # an AI horizontal hint (older verdicts) still beats saliency for where to centre
    if "subject_x" in ai and ai.get("subject_x") not in (None, 0.5):
        shift = float(ai["subject_x"]) - box["cx"]
        box = make_box(box["x0"] + shift, box["y0"], box["x1"] + shift, box["y1"])
    box["source"] = "saliency"
    return box


def crop_fraction(w: int, h: int) -> float:
    """Width of a 9:16 crop as a fraction of a (wider) source frame."""
    return min(1.0, (h * OUT_W / OUT_H) / max(w, 1))


def decide_layout(shot: dict, box: dict, want: str) -> tuple[str, dict]:
    """Pick crop/pan/blur_fill for a landscape source so the subject survives the vertical cut."""
    w, h = shot["w"], shot["h"]
    ar = w / max(h, 1)
    if ar <= 0.75:
        return "fill", {}
    if want not in ("auto", None):
        return want, ({"pan_from": box["x0"], "pan_to": box["x1"]} if want == "pan" else {})
    cf = crop_fraction(w, h)
    bw = box["x1"] - box["x0"]
    if bw <= cf * 0.95:
        return "crop", {}
    if bw <= cf * 2.6 or ar > 2.1:
        # subject wider than the vertical window: travel across it, starting from its brighter side
        return "pan", {"pan_from": box["x0"], "pan_to": box["x1"]}
    return "blur_fill", {}


# --------------------------------------------------------------- tracking
def track_x(src: str, t_in: float, src_len: float, info: dict, prior_cx: float,
            fps: float = 5.0) -> list[tuple[float, float]] | None:
    """Follow a moving subject horizontally inside one clip window.

    Returns [(t_out_seconds, cx_normalised), ...] smoothed, or None if the subject
    barely moves (a static crop is calmer)."""
    w = 128
    h = max(8, int(w * info["src_h"] / max(info["src_w"], 1)))
    # decode a few seconds either side too: a slow subject needs a long span for a clean background
    margin = 4.0
    t0 = max(0.0, t_in - margin)
    vf = [f"fps={fps}", f"scale={w}:{h}:flags=area"] + hdr_chain(info) + ["format=rgb24"]
    cmd = ffmpeg_base() + ["-ss", f"{t0:.3f}", "-t", f"{src_len + (t_in - t0) + margin:.3f}", "-i", src, "-an",
                           "-vf", ",".join(vf), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    out = subprocess.run(cmd, capture_output=True).stdout
    n_all = len(out) // (w * h * 3)
    if n_all < 4:
        return None
    allf = np.frombuffer(out[: n_all * w * h * 3], np.uint8).reshape(n_all, h, w, 3)
    i0 = int(round((t_in - t0) * fps))
    frames = allf[i0:i0 + max(4, int(round(src_len * fps)) + 1)]
    if len(frames) < 4:
        return None
    xs = _motion_track(frames, allf)
    if xs is None:
        # camera itself moves (or nothing moves): follow what stands out, anchored to the prior
        xs = np.array([box_from_map(saliency_map(f, width=w))["cx"] for f in frames])
        xs = 0.6 * xs + 0.4 * prior_cx
        k = max(3, int(fps * 1.2) | 1)
        max_step = 0.12 / fps
    else:
        k = max(3, int(fps * 0.6) | 1)  # real motion: lighter smoothing, allow faster follow
        max_step = 0.3 / fps
    pad = k // 2
    xs_s = np.convolve(np.pad(xs, pad, mode="edge"), np.ones(k) / k, mode="valid")
    if xs_s.max() - xs_s.min() < 0.04 and abs(float(xs_s.mean()) - prior_cx) < 0.08:
        return None
    for i in range(1, len(xs_s)):
        xs_s[i] = xs_s[i - 1] + np.clip(xs_s[i] - xs_s[i - 1], -max_step, max_step)
    speed = float(info.get("speed", 1.0))
    return [(i / fps / speed, float(x)) for i, x in enumerate(xs_s)]


def _motion_track(frames: np.ndarray, context: np.ndarray | None = None) -> np.ndarray | None:
    """Horizontal centre of whatever moves against a still background, per frame.

    Uses the per-pixel median over the window as the background. Returns None when the
    camera moves (most of the frame changes) or nothing does."""
    def g(fs):
        return np.stack([cv2.GaussianBlur(cv2.cvtColor(f, cv2.COLOR_RGB2GRAY), (5, 5), 0) for f in fs]).astype(np.int16)
    gray = g(frames)
    bg = np.median(g(context) if context is not None and len(context) > len(frames) else gray, axis=0)
    h, w = gray.shape[1:]
    xs, fracs = [], []
    cols = np.arange(w)
    for g in gray:
        m = np.abs(g - bg) > 22
        m = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)).astype(bool)
        frac = m.mean()
        fracs.append(frac)
        colsum = m.sum(0)
        xs.append(float((colsum * cols).sum() / colsum.sum() / w) if colsum.sum() > 3 else np.nan)
    fracs = np.array(fracs)
    xs = np.array(xs)
    good = ~np.isnan(xs)
    # a tracked subject: something moves in most frames, but only a small part of the frame
    if good.mean() < 0.6 or np.median(fracs) > 0.25 or np.median(fracs) < 0.0015:
        return None
    idx = np.arange(len(xs))
    xs[~good] = np.interp(idx[~good], idx[good], xs[good])
    return xs


def piecewise_expr(points: list[tuple[float, float]], lo: float, hi: float) -> str:
    """ffmpeg expression for a piecewise-linear x(t) through points (pixels), clamped."""
    pts = [(t, float(np.clip(x, lo, hi))) for t, x in points]
    if len(pts) > 24:  # keep the expression short: resample
        idx = np.linspace(0, len(pts) - 1, 24).round().astype(int)
        pts = [pts[i] for i in idx]
    expr = f"{pts[-1][1]:.1f}"
    for (t0, x0), (t1, x1) in reversed(list(zip(pts[:-1], pts[1:]))):
        if t1 - t0 < 1e-3:
            continue
        seg = f"{x0:.1f}+({x1 - x0:.1f})*(t-{t0:.3f})/{t1 - t0:.3f}"
        expr = f"if(lt(t\\,{t1:.3f})\\,{seg}\\,{expr})"
    return f"if(lt(t\\,{pts[0][0]:.3f})\\,{pts[0][1]:.1f}\\,{expr})"
