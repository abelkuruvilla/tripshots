"""2.5D parallax for photos: the foreground slides against the background, so a still feels like a camera move.

A depth map is made once per photo (cached in the library): with Depth Anything V2 Small (Apache-2.0; ONNX,
about 27 MB, downloaded once to ~/.tripshots/models on first use) when it can be had, else an estimate from the
picture itself (sky far away, the bottom of the frame and the salient subject near). During the shot every
pixel is shifted by an amount that grows with its nearness, as the camera drifts: near things move more.
Things that stand out in front (a person, a rock, a tree) move as one rigid layer: inside them the depth is
flattened (rigid_layers), so only the background just outside their edge stretches and the subject never bends.
`TRIPSHOTS_OFFLINE=1` never downloads.
"""
from __future__ import annotations

import os
import urllib.request
from pathlib import Path

import cv2
import numpy as np

from .config import HOME
from .util import log

MODEL_URL = os.environ.get("TRIPSHOTS_DEPTH_MODEL_URL",
                           "https://huggingface.co/onnx-community/depth-anything-v2-small/resolve/main/onnx/"
                           "model_quantized.onnx")
MODEL = HOME / "models" / "depth_anything_v2_small_q.onnx"
CACHE = HOME / "library" / "depth"
_session = None
_failed = False


def _model():
    global _session, _failed
    if _session is not None or _failed:
        return _session
    try:
        import onnxruntime as ort
    except ImportError:
        _failed = True
        return None
    if not MODEL.exists():
        if os.environ.get("TRIPSHOTS_OFFLINE"):
            _failed = True
            return None
        try:
            MODEL.parent.mkdir(parents=True, exist_ok=True)
            log("parallax: downloading the depth model (Depth Anything V2 Small, ~27 MB, once)")
            tmp = MODEL.with_suffix(".part")
            urllib.request.urlretrieve(MODEL_URL, tmp)
            tmp.replace(MODEL)
        except Exception as e:
            log(f"parallax: depth model unavailable ({str(e)[:100]}); estimating depth from the picture")
            _failed = True
            return None
    try:
        _session = ort.InferenceSession(str(MODEL), providers=["CPUExecutionProvider"])
    except Exception as e:
        log(f"parallax: depth model didn't load ({str(e)[:100]}); estimating depth from the picture")
        _failed = True
    return _session


def _model_depth(rgb: np.ndarray) -> np.ndarray | None:
    sess = _model()
    if sess is None:
        return None
    h, w = rgb.shape[:2]
    s = 518 / max(h, w)
    nh, nw = max(14, int(round(h * s / 14)) * 14), max(14, int(round(w * s / 14)) * 14)
    x = cv2.resize(rgb, (nw, nh), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
    x = (x - np.array([0.485, 0.456, 0.406], np.float32)) / np.array([0.229, 0.224, 0.225], np.float32)
    x = x.transpose(2, 0, 1)[None]
    try:
        name = sess.get_inputs()[0].name
        d = np.squeeze(sess.run(None, {name: x})[0]).astype(np.float32)  # relative inverse depth: big = near
    except Exception as e:
        log(f"parallax: depth model failed ({str(e)[:100]})")
        return None
    d = (d - np.percentile(d, 2)) / max(1e-6, np.percentile(d, 98) - np.percentile(d, 2))
    return np.clip(d, 0, 1)


def _estimate_depth(rgb: np.ndarray) -> np.ndarray:
    """No model: sky = far, lower in the frame = nearer, the salient subject a little nearer still."""
    h, w = rgb.shape[:2]
    d = np.tile(np.linspace(0.15, 1.0, h, dtype=np.float32)[:, None] ** 1.3, (1, w))
    try:
        from .mask import sky_mask
        sky = sky_mask(rgb)
        if sky is not None:
            sky = cv2.resize(sky.astype(np.float32), (w, h), interpolation=cv2.INTER_LINEAR)
            sky *= np.linspace(1, 0, h, dtype=np.float32)[:, None] > 0.3  # never the bottom of the frame
            d = d * (1 - sky)
    except Exception:
        pass
    try:
        from .framing import saliency_map
        sal = cv2.resize(saliency_map(rgb, width=96), (w, h), interpolation=cv2.INTER_LINEAR)
        d = np.clip(d + 0.25 * sal, 0, 1)
    except Exception:
        pass
    return d


def depth(rgb: np.ndarray, key: str | None = None) -> np.ndarray:
    """Depth 0 (far) .. 1 (near) at the image's size, smoothed so shifting it never tears edges apart."""
    p = CACHE / f"{key}.npy" if key else None
    small = None
    if p and p.exists():
        try:
            small = np.load(p)
        except Exception:
            small = None
    if small is None:
        h, w = rgb.shape[:2]
        s = 640 / max(h, w)
        work = cv2.resize(rgb, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA) if s < 1 else rgb
        small = _model_depth(work)
        if small is None:
            small = _estimate_depth(work)
        small = small.astype(np.float16)
        if p:
            p.parent.mkdir(parents=True, exist_ok=True)
            np.save(p, small)
    d = cv2.resize(small.astype(np.float32), (rgb.shape[1], rgb.shape[0]), interpolation=cv2.INTER_LINEAR)
    k = max(3, int(min(d.shape) * 0.02) | 1)
    return cv2.GaussianBlur(d, (k, k), 0)


def rigid_layers(d: np.ndarray) -> np.ndarray:
    """The depth with every object that stands out in front made flat (one value per object), and the step at
    its edge moved outside it: shifting by this depth slides a person across the view without bending them."""
    h, w = d.shape[:2]
    s = min(1.0, 480 / max(h, w))
    ds = cv2.resize(d, (max(8, int(w * s)), max(8, int(h * s))), interpolation=cv2.INTER_AREA) if s < 1 else d.copy()
    sh, sw = ds.shape[:2]
    k = max(5, int(0.18 * max(sh, sw)) | 1)
    bg = cv2.morphologyEx(ds, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    obj = ((ds - bg) > 0.06).astype(np.uint8)  # nearer than what is around it: something standing in front
    obj = cv2.morphologyEx(obj, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(obj, 8)
    flat = ds.copy()
    keep = np.zeros_like(obj)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] < 0.003 * sh * sw:
            continue
        m = lab == i
        flat[m] = float(np.percentile(ds[m], 60))
        keep[m] = 1
    if keep.any():  # the step from the object to what is behind it happens in a ring outside the object
        ring = max(3, int(0.04 * max(sh, sw)))
        dist, idx = cv2.distanceTransformWithLabels(1 - keep, cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL)
        ys, xs = np.nonzero(keep)
        near = np.zeros(int(idx.max()) + 1, np.float32)
        near[idx[ys, xs]] = flat[ys, xs]  # each pixel outside takes the value of the nearest object pixel
        val = near[idx]
        wgt = np.clip(1.0 - dist / ring, 0, 1) * (1 - keep)
        flat = np.where(keep > 0, flat, wgt * np.maximum(val, ds) + (1 - wgt) * ds)
    return cv2.resize(flat, (w, h), interpolation=cv2.INTER_LINEAR) if s < 1 else flat


def worth_it(d: np.ndarray) -> bool:
    """A flat picture (a wall, a distant ridge) gains nothing from parallax."""
    return float(np.percentile(d, 90) - np.percentile(d, 10)) > 0.25


class Mover:
    """Per-frame parallax shift on top of the Ken Burns crop."""

    def __init__(self, src: np.ndarray, d: np.ndarray, amp_px: float, direction: float = 1.0):
        self.d = rigid_layers(d.astype(np.float32))
        self.mid = float(np.median(self.d))
        self.amp = float(amp_px)
        self.dir = direction
        self.grid = None

    def frame(self, fr: np.ndarray, M: np.ndarray, p: float) -> np.ndarray:
        oh, ow = fr.shape[:2]
        dw = cv2.warpAffine(self.d, M, (ow, oh), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        if self.grid is None or self.grid[0].shape != (oh, ow):
            gx, gy = np.meshgrid(np.arange(ow, dtype=np.float32), np.arange(oh, dtype=np.float32))
            self.grid = (gx, gy)
        gx, gy = self.grid
        t = (p - 0.5) * 2 * self.dir                      # camera drifts from one side to the other
        off = (dw - self.mid) * self.amp * t
        return cv2.remap(fr, gx - off, gy - 0.25 * off, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
