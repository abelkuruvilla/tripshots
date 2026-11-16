"""Secondary colour grading: layers on parts of the frame, like a colourist's serial nodes after the primary grade.

The primary grade (grade.py) is one 3D LUT per shot: balance, then the look, for the whole picture. A layer works on
one region of the picture, found in every frame:

  sky      the sky (mask.py: smooth, sky-coloured, connected to the top)
  subject  a soft window around the person (faces, YuNet, widened to the body) or the shot's subject box
  skin     skin tones inside the subject's window (a hue/saturation/brightness qualifier)
  greens   foliage (a qualifier on green hues, outside the sky)
  water    blue and cyan below the sky (sea, lakes, rivers)
  ground   the lower part of the frame, feathered from the horizon (a graduated filter)
  edges    everything away from the subject (darken it to guide the eye: a relight / vignette)

and changes it: exposure (stops), contrast, saturation, warmth, tint, hue (degrees). A segment's `layers` is a list
of {"region", ...adjustments, "on", "auto"}. Masks are made at a small size, feathered, and smoothed over time so
nothing flickers; then each layer is one 3x4 colour matrix blended through its mask. Layers are applied where the
frames are put together (render's compositor and the editor's stills), so changing one never re-renders a shot.
"""
from __future__ import annotations

import math

import cv2
import numpy as np

REGIONS = ("sky", "subject", "skin", "greens", "water", "ground", "edges")
RANGES = {"exposure": (-1.5, 1.5, 0.0), "contrast": (0.6, 1.5, 1.0), "saturation": (0.0, 2.0, 1.0),
          "warmth": (-1.0, 1.0, 0.0), "tint": (-1.0, 1.0, 0.0), "hue": (-45.0, 45.0, 0.0)}
WORK_W = 270          # masks are worked out at this width
LUMA = np.array([0.2126, 0.7152, 0.0722], np.float32)


# ------------------------------------------------------------------ adjustments -> one colour matrix
def clean(layer: dict) -> dict:
    """A layer with its values in range (unknown keys dropped)."""
    out = {"region": layer["region"]}
    for k, (lo, hi, n) in RANGES.items():
        if k in layer and layer[k] is not None:
            v = float(layer[k])
            if abs(v - n) > 1e-4:
                out[k] = round(max(lo, min(hi, v)), 3)
    for k in ("on", "auto", "why"):
        if k in layer:
            out[k] = layer[k]
    return out


def matrix(layer: dict) -> np.ndarray:
    """The layer's adjustments as a 3x4 matrix on RGB 0..1 (display-referred, close enough for gentle moves)."""
    M = np.eye(3, dtype=np.float32)
    off = np.zeros(3, np.float32)
    # saturation around luma
    s = float(layer.get("saturation", 1.0))
    if s != 1.0:
        M = (s * np.eye(3) + (1 - s) * np.outer(np.ones(3), LUMA)).astype(np.float32) @ M
    # hue: rotate around the grey axis
    h = math.radians(float(layer.get("hue", 0.0)))
    if h:
        c, si = math.cos(h), math.sin(h)
        k = 1 / math.sqrt(3)
        K = np.array([[0, -k, k], [k, 0, -k], [-k, k, 0]], np.float32)
        R = np.eye(3, dtype=np.float32) + si * K + (1 - c) * (K @ K)
        M = R @ M
    # warmth (red up, blue down) and tint (green down = magenta)
    w, t = float(layer.get("warmth", 0.0)), float(layer.get("tint", 0.0))
    if w or t:
        M = np.diag([1 + 0.12 * w, 1 - 0.07 * t, 1 - 0.12 * w]).astype(np.float32) @ M
    # contrast around the middle grey
    c = float(layer.get("contrast", 1.0))
    if c != 1.0:
        M = c * M
        off = c * off + (1 - c) * 0.42
    # exposure (stops, on gamma-encoded values: 2^(e / 2.2))
    e = float(layer.get("exposure", 0.0))
    if e:
        g = 2 ** (e / 2.2)
        M, off = g * M, g * off
    return np.concatenate([M, off[:, None]], 1).astype(np.float32)


# ------------------------------------------------------------------ regions
def _smooth(x, e0, e1):
    t = np.clip((x - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


_det = None
_cut = None


def cutout(small_rgb: np.ndarray) -> np.ndarray | None:
    """The main subject's soft mask (0..1) from a quick cut-out (rembg's small u2netp model), or None."""
    global _cut
    try:
        from .popout import have_cutout
        if not have_cutout():
            return None
        from PIL import Image
        from rembg import new_session, remove
        if _cut is None:
            _cut = new_session("u2netp")
        return np.asarray(remove(Image.fromarray(small_rgb), session=_cut, only_mask=True)).astype(np.float32) / 255
    except Exception:
        _cut = _cut or False
        return None


def people_mask(frame_rgb: np.ndarray, width: int = 360) -> np.ndarray | None:
    """The people in a frame as a soft mask at the frame's size (for a silhouette flash), or None when the cut-out
    finds no clear figure (nothing, or most of the frame)."""
    import cv2
    h, w = frame_rgb.shape[:2]
    small = cv2.resize(frame_rgb, (width, max(2, int(round(width * h / w)))), interpolation=cv2.INTER_AREA)
    m = cutout(small)
    if m is None or not 0.01 < float((m > 0.5).mean()) < 0.4:
        return None
    # keep the upright, figure-shaped parts only (a person standing or sitting up): the cut-out finds whatever
    # stands out, and a truck or a log flashing white isn't the effect
    n, lab, st, _ = cv2.connectedComponentsWithStats((m > 0.5).astype(np.uint8))
    keep = [k for k in range(1, n) if st[k, cv2.CC_STAT_AREA] > 0.002 * m.size
            and st[k, cv2.CC_STAT_HEIGHT] >= 1.15 * st[k, cv2.CC_STAT_WIDTH]]
    if not keep:
        return None
    m = m * np.isin(lab, keep).astype(np.float32)
    m = cv2.GaussianBlur(cv2.resize(m, (w, h), interpolation=cv2.INTER_LINEAR), (0, 0), max(1.0, w / 900))
    return np.clip((m - 0.35) / 0.3, 0, 1).astype(np.float32)


def _subject_box(small_rgb: np.ndarray) -> tuple[float, float, float, float] | None:
    """The main subject's ellipse (cx, cy, rx, ry) 0..1 from a quick cut-out (rembg's small u2netp model, a few MB,
    fetched once), or None when there's no clear subject or no rembg."""
    global _cut
    try:
        from .popout import have_cutout
        if not have_cutout():
            return None
        from PIL import Image
        from rembg import new_session, remove
        if _cut is None:
            _cut = new_session("u2netp")
        m = np.asarray(remove(Image.fromarray(small_rgb), session=_cut, only_mask=True)).astype(np.float32) / 255
    except Exception:
        _cut = _cut or False
        return None
    on = m > 0.5
    share = float(on.mean())
    if not 0.004 < share < 0.55:
        return None
    ys, xs = np.nonzero(on)
    h, w = m.shape
    x0, x1, y0, y1 = xs.min() / w, xs.max() / w, ys.min() / h, ys.max() / h
    return ((x0 + x1) / 2, (y0 + y1) / 2, max(0.06, (x1 - x0) * 0.62), max(0.06, (y1 - y0) * 0.62 * h / w))


def sky_region(small_rgb: np.ndarray) -> np.ndarray:
    """Everything above the skyline (clouds included), soft at the horizon; zeros when there's no sky."""
    from .mask import sky_mask
    fg = sky_mask(small_rgb)
    h, w = small_rgb.shape[:2]
    if fg is None:
        return np.zeros((h, w), np.float32)
    sky = fg < 0.5
    rows = np.arange(h)[:, None]
    low = np.where(sky.any(axis=0), np.where(sky, rows, -1).max(axis=0), -1).astype(np.float32)  # lowest sky row
    have = low >= 0
    if have.sum() < 0.2 * w:
        return (1 - fg).astype(np.float32)
    low = np.interp(np.arange(w), np.nonzero(have)[0], low[have])
    low = cv2.GaussianBlur(cv2.medianBlur(low.astype(np.float32).reshape(1, -1), 5), (0, 0), 3).ravel()
    feather = max(2.0, 0.03 * h)
    return (1 - _smooth(rows.astype(np.float32), low[None, :] - feather, low[None, :] + feather)).astype(np.float32)


def _faces(small_bgr: np.ndarray) -> list[tuple[float, float, float, float]]:
    """Faces as (x, y, w, h) 0..1, when the face model is on this computer (never downloaded here)."""
    global _det
    try:
        from .people import MODEL_DIR, MODELS
        p = MODEL_DIR / MODELS["yunet"]["file"]
        if not p.exists():
            return []
        if _det is None:
            _det = cv2.FaceDetectorYN.create(str(p), "", (320, 320), 0.75, 0.3, 20)
        h, w = small_bgr.shape[:2]
        _det.setInputSize((w, h))
        _, rows = _det.detect(small_bgr)
        return [(float(f[0]) / w, float(f[1]) / h, float(f[2]) / w, float(f[3]) / h) for f in rows] if rows is not None else []
    except Exception:
        return []


def subject_window(seg: dict, canvas: tuple[int, int]) -> tuple[float, float, float, float] | None:
    """Where the shot's subject sits in the output frame, (cx, cy, rx, ry) 0..1, from the plan's subject box."""
    sb = seg.get("subject") or {}
    so = seg.get("subject_out") or {}
    if "cx" not in sb or "y0" not in so:
        return None
    W, H = canvas
    cx = float(sb["cx"])
    if seg.get("layout") == "crop" and seg.get("src_w") and seg.get("src_h"):
        sw = seg["src_w"] * H / seg["src_h"] if seg["src_w"] / seg["src_h"] > W / H else W
        x0 = max(0.0, min(sw - W, cx * sw - W / 2))
        cx = (cx * sw - x0) / W
    elif seg.get("layout") in ("pan", "kenburns", "blur_fill", None):
        cx = 0.5 + (cx - 0.5) * 0.4
    y0, y1 = float(so["y0"]), float(so["y1"])
    bw = max(0.12, (float(sb.get("x1", cx + 0.1)) - float(sb.get("x0", cx - 0.1))))
    return (min(0.95, max(0.05, cx)), (y0 + y1) / 2, min(0.45, bw * 0.9 + 0.12), min(0.45, (y1 - y0) * 0.75 + 0.1))


class Masks:
    """The regions of one shot's frames, worked out at a small size and smoothed over time."""

    def __init__(self, seg: dict, canvas: tuple[int, int]):
        self.seg = seg
        self.canvas = canvas
        self.prev: dict[str, np.ndarray] = {}
        self.faces: list = []
        self.n = 0

    def get(self, frame: np.ndarray, wanted: set[str], still: bool = False) -> dict[str, np.ndarray]:
        H, W = frame.shape[:2]
        h = max(8, int(WORK_W * H / W))
        small = cv2.resize(frame, (WORK_W, h), interpolation=cv2.INTER_AREA)
        lab = cv2.cvtColor(small.astype(np.float32) / 255, cv2.COLOR_RGB2LAB)
        L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
        C = np.hypot(a, b)
        hue = np.degrees(np.arctan2(b, a)) % 360
        out: dict[str, np.ndarray] = {}
        sky = None
        need_subject = bool(wanted & {"subject", "skin", "edges", "sky"})
        if need_subject and (still or self.n % 36 == 0):
            # who is in the frame, a few times a second: faces (widened to head, shoulders and body), else the
            # main subject from a quick cut-out; the window holds between looks and moves smoothly (below)
            self.faces = _faces(cv2.cvtColor(small, cv2.COLOR_RGB2BGR))
            boxes = [(fx + fw / 2, fy + fh * 1.6, fw * 1.9, fh * 2.6) for (fx, fy, fw, fh) in self.faces]
            if not boxes and (sb := _subject_box(small)):
                boxes.append(sb)
            if not boxes and (sw := subject_window(self.seg, self.canvas)):
                boxes.append(sw)
            self.boxes = boxes
        boxes = getattr(self, "boxes", [])
        win = None
        if need_subject:
            yy, xx = np.mgrid[0:h, 0:WORK_W].astype(np.float32)
            xx, yy = xx / WORK_W, yy / h
            win = np.zeros((h, WORK_W), np.float32)
            for cx, cy, rx, ry in boxes:
                d = ((xx - cx) / max(rx, 1e-3)) ** 2 + ((yy - cy) / max(ry * W / H, 1e-3)) ** 2
                win = np.maximum(win, 1 - _smooth(d, 0.35, 1.0))
        if wanted & {"sky", "water", "greens", "ground"}:
            # the sky every third frame (it moves slowly; the smoothing below carries it in between)
            if still or self.n % 3 == 0 or getattr(self, "sky", None) is None:
                self.sky = sky_region(small)
            sky = self.sky
            if win is not None:   # a head against the sky is not sky
                sky = sky * (1 - _smooth(win, 0.1, 0.5))
            out["sky"] = sky.astype(np.float32)
        if wanted & {"subject", "skin", "edges"}:
            out["subject"] = win
            out["edges"] = 1 - _smooth(win, 0.0, 0.6) if boxes else \
                _smooth(((xx - 0.5) / 0.55) ** 2 + ((yy - 0.48) / 0.6) ** 2, 0.5, 1.4)
            skin_q = (_smooth(hue, 20, 32) * (1 - _smooth(hue, 70, 84)) * _smooth(C, 7, 12) * (1 - _smooth(C, 42, 55))
                      * _smooth(L, 22, 32) * (1 - _smooth(L, 88, 96)))
            out["skin"] = skin_q * _smooth(win, 0.15, 0.5) if self.faces else np.zeros_like(win)
        if "greens" in wanted:
            g = _smooth(hue, 92, 108) * (1 - _smooth(hue, 160, 178)) * _smooth(C, 6, 14) * _smooth(L, 8, 18)
            out["greens"] = g * (1 - sky)
        if "water" in wanted:
            wq = _smooth(hue, 170, 188) * (1 - _smooth(hue, 285, 300)) * _smooth(C, 5, 12) * _smooth(L, 8, 16)
            out["water"] = wq * (1 - _smooth(sky, 0.2, 0.6))
        if "ground" in wanted:
            rows = sky.mean(axis=1)
            horizon = float(np.argmax(rows < 0.5)) / h if (rows < 0.5).any() and rows[0] > 0.5 else 0.45
            yy = np.linspace(0, 1, h, dtype=np.float32)[:, None]
            out["ground"] = np.repeat(_smooth(yy, horizon + 0.08, min(1.0, horizon + 0.45)), WORK_W, 1)
        k = 0.0 if still else 0.6    # smoothing over time: masks follow the picture without flicker
        res = {}
        for name in wanted:
            m = out.get(name)
            if m is None:
                continue
            m = cv2.GaussianBlur(m.astype(np.float32), (0, 0), 2.0 if name in ("sky", "ground") else 1.5)
            if k and name in self.prev:
                m = k * self.prev[name] + (1 - k) * m
            self.prev[name] = m
            res[name] = m
        self.n += 1
        return res


def apply(frame: np.ndarray, layers: list[dict], masks: Masks, still: bool = False) -> np.ndarray:
    """The frame with the shot's layers applied, in order (each sees the result of the one before)."""
    live = [l for l in layers if l.get("on", True) and l.get("region") in REGIONS
            and any(k in l for k in RANGES)]
    if not live:
        return frame
    H, W = frame.shape[:2]
    ms = masks.get(frame, {l["region"] for l in live}, still=still)
    x = np.ascontiguousarray(frame)
    for l in live:
        m = ms.get(l["region"])
        if m is None or float(m.max()) < 0.02:
            continue
        m = np.clip(cv2.resize(m, (W, H), interpolation=cv2.INTER_LINEAR), 0, 1)
        M = matrix(l)
        M[:, 3] *= 255   # the offset in 8-bit units
        y = cv2.transform(x, M)                    # 8-bit in, saturating: fast and exact enough for gentle moves
        x = cv2.blendLinear(y, x, m, 1 - m)        # through the region's soft mask
    return x


def mask_view(frame: np.ndarray, region: str, seg: dict) -> np.ndarray:
    """The frame with one region shown (the rest dimmed, the region tinted), for the editor's mask view."""
    m = Masks(seg, (frame.shape[1], frame.shape[0])).get(frame, {region}, still=True).get(region)
    if m is None:
        return frame
    m = cv2.resize(m, (frame.shape[1], frame.shape[0]))[..., None]
    x = frame.astype(np.float32)
    dim = x * 0.28
    hi = x * 0.75 + np.array([232, 116, 63], np.float32) * 0.25
    return np.clip(dim + (hi - dim) * m, 0, 255).astype(np.uint8)


# ------------------------------------------------------------------ automatic layers (no AI)
def auto_layers(thumb_rgb: np.ndarray, seg: dict, look: dict | None, people: bool) -> list[dict]:
    """What a colourist would usually do to this shot, from its thumbnail: hold back a bright sky, lift a subject
    left in shade, keep skin natural, and add depth by easing the edges down. Gentle, and marked `auto`."""
    canvas = (thumb_rgb.shape[1], thumb_rgb.shape[0])
    wanted = {"sky", "subject", "edges"} | ({"skin"} if people else set())
    ms = Masks(seg, canvas).get(thumb_rgb, wanted, still=True)
    small = cv2.resize(thumb_rgb, (WORK_W, ms["sky"].shape[0] if "sky" in ms else int(WORK_W * thumb_rgb.shape[0] / thumb_rgb.shape[1])))
    L = cv2.cvtColor(small.astype(np.float32) / 255, cv2.COLOR_RGB2LAB)[..., 0]
    mean = float(L.mean())
    out = []

    def avg(m):
        m = cv2.resize(m, (L.shape[1], L.shape[0]))
        return float((L * m).sum() / max(1e-3, m.sum())), float(m.mean())
    sky_L, sky_share = avg(ms["sky"]) if "sky" in ms else (0, 0)
    if sky_share > 0.08 and sky_L > 72:   # a bright sky: hold it back so it has colour and the land leads
        out.append({"region": "sky", "exposure": round(-min(0.45, (sky_L - 68) / 60), 2), "saturation": 1.12,
                    "why": "bright sky held back", "auto": True})
    if people and "subject" in ms:
        subj_L, subj_share = avg(ms["subject"])
        if 0.01 < subj_share < 0.6 and subj_L < mean - 6:   # the person is darker than the scene: relight
            out.append({"region": "subject", "exposure": round(min(0.45, (mean - subj_L) / 45), 2),
                        "why": "subject lifted out of the shade", "auto": True})
        if not (look or {}).get("mono"):
            out.append({"region": "skin", "saturation": 1.08, "warmth": 0.1, "why": "skin kept natural", "auto": True})
    if not seg.get("panel"):
        out.append({"region": "edges", "exposure": -0.18, "why": "edges eased down for depth", "auto": True})
    return [clean(l) for l in out]
