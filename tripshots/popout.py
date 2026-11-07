"""'Out of frame' / pop-out effect: the photo sits in a frame on a paper (or blurred, or plain)
background and the subject breaks out past the frame edge.

Cut-out uses rembg (MIT; IS-Net / U2-Net models, run locally, downloaded once to ~/.u2net).
Masks are cached per photo in the library, so each photo is only segmented once.

Two variants, picked automatically:
  top     the subject's head and shoulders rise above the frame's top edge
  bottom  the subject's legs / the rock it stands on spill below the frame's bottom edge
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from . import library as lib
from .util import ReelError, log

MASKS = lib.LIB_DIR / "masks"
FORMATS = {"post": (1080, 1350), "story": (1080, 1920), "square": (1080, 1080)}
_sessions: dict = {}


def have_cutout() -> bool:
    try:
        import importlib.util
        return importlib.util.find_spec("rembg") is not None
    except Exception:
        return False


def subject_mask(rgb: np.ndarray, key: str, model: str = "isnet-general-use") -> np.ndarray:
    """Float mask 0..1 of the main subject (cached by key)."""
    MASKS.mkdir(parents=True, exist_ok=True)
    p = MASKS / f"{key}_{model}.png"
    if p.exists():
        m = np.asarray(Image.open(p)).astype(np.float32) / 255.0
        if m.shape[:2] == rgb.shape[:2]:
            return m
    if not have_cutout():
        raise ReelError("the pop-out frame needs rembg: re-run ./install.sh (or `pip install \"rembg[cpu]\"`)")
    from rembg import new_session, remove
    if model not in _sessions:
        log(f"loading cut-out model {model} (first time downloads ~170 MB)")
        _sessions[model] = new_session(model)
    # segment at ~1024 px on the long side (model works at 1024; keeps it fast), upsample the matte
    h, w = rgb.shape[:2]
    f = min(1.0, 1280 / max(h, w))
    small = Image.fromarray(rgb).resize((int(w * f), int(h * f)), Image.Resampling.LANCZOS) if f < 1 else Image.fromarray(rgb)
    m = np.asarray(remove(small, session=_sessions[model], only_mask=True)).astype(np.float32) / 255.0
    if f < 1:
        m = cv2.resize(m, (w, h), interpolation=cv2.INTER_LINEAR)
    Image.fromarray((m * 255).astype(np.uint8)).save(p)
    return m


def mask_box(m: np.ndarray, thr: float = 0.5):
    ys, xs = np.nonzero(m > thr)
    if len(xs) < 50:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def usable(m: np.ndarray) -> tuple[bool, str]:
    """Is there one clear subject to pop out?"""
    area = float((m > 0.5).mean())
    if area < 0.005:
        return False, "no clear subject"
    if area > 0.55:
        return False, "subject fills the photo"
    n, lbl, stats, _ = cv2.connectedComponentsWithStats((m > 0.5).astype(np.uint8), 8)
    if n <= 1:
        return False, "no subject"
    main = stats[1:, cv2.CC_STAT_AREA].max()
    if main < 0.6 * stats[1:, cv2.CC_STAT_AREA].sum():
        return False, "subject is in pieces"
    return True, "ok"


# ------------------------------------------------------------ backgrounds
def paper(w: int, h: int, tone=(236, 229, 216), seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    base = np.empty((h, w, 3), np.float32)
    base[:] = tone
    grain = rng.normal(0, 1, (h // 2, w // 2)).astype(np.float32)
    grain = cv2.resize(cv2.GaussianBlur(grain, (0, 0), 0.8), (w, h)) * 3.2
    fibres = cv2.resize(rng.normal(0, 1, (h // 24, w // 24)).astype(np.float32), (w, h),
                        interpolation=cv2.INTER_CUBIC) * 2.0
    base += (grain + fibres)[..., None]
    yy, xx = np.mgrid[0:h, 0:w]
    vig = 1 - 0.06 * (((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2)
    return np.clip(base * vig[..., None], 0, 255).astype(np.uint8)


def background(kind: str, w: int, h: int, photo: np.ndarray) -> np.ndarray:
    if kind == "blur":
        cover = _cover(photo, w, h)
        small = cv2.resize(cover, (w // 8, h // 8), interpolation=cv2.INTER_AREA)
        small = cv2.GaussianBlur(small, (0, 0), 6)
        return cv2.convertScaleAbs(cv2.resize(small, (w, h)), alpha=0.62)
    if kind == "dark":
        return paper(w, h, tone=(24, 24, 26))
    if kind == "solid":  # a muted colour taken from the photo
        c = cv2.resize(photo, (1, 1), interpolation=cv2.INTER_AREA)[0, 0].astype(np.float32)
        c = 0.35 * c + 0.65 * np.array([236, 229, 216])
        return paper(w, h, tone=tuple(int(v) for v in c))
    return paper(w, h)


def _cover(img: np.ndarray, w: int, h: int) -> np.ndarray:
    ih, iw = img.shape[:2]
    s = max(w / iw, h / ih)
    r = cv2.resize(img, (int(iw * s + 1), int(ih * s + 1)), interpolation=cv2.INTER_AREA)
    y0, x0 = (r.shape[0] - h) // 2, (r.shape[1] - w) // 2
    return r[y0:y0 + h, x0:x0 + w]


# ------------------------------------------------------------- layout
def plan_layout(photo_shape, box, W: int, H: int, variant: str = "auto") -> dict:
    """Where the frame goes on the canvas and how the photo maps onto it.

    top:    the frame's top edge cuts the subject at ~30% of its height (head + shoulders out)
    bottom: the frame's bottom edge cuts it at ~70% (legs / what it stands on spill out)"""
    ph, pw = photo_shape[:2]
    bx0, by0, bx1, by1 = box
    bh = by1 - by0
    if variant == "auto":
        touches_bottom = by1 >= ph * 0.97
        variant = "top" if (by0 / ph >= 0.08 or touches_bottom) else "bottom"
    frame_w = int(W * 0.68) // 2 * 2
    frame_h = int(min(H * 0.58, frame_w / 0.74)) // 2 * 2
    if variant == "top":
        cut = by0 + 0.30 * bh                     # photo row on the frame's top edge
        s_fit = frame_h / max(1.0, ph - cut)      # frame must stay inside the photo below the cut
    else:
        cut = by0 + 0.70 * bh                     # photo row on the frame's bottom edge
        s_fit = frame_h / max(1.0, cut)
    s = max(s_fit, frame_w / pw, 0.75 * frame_h / max(1.0, bh))
    s = min(s, max(s_fit, frame_w / pw) * 1.6)    # don't blow the photo up too far
    # outside-the-frame part of the subject (canvas px) decides the vertical placement
    out_px = (cut - by0) * s if variant == "top" else (by1 - cut) * s
    frame_h = min(frame_h, int(H * 0.9 - out_px - H * 0.05)) // 2 * 2
    if variant == "top":
        fy = int(max(H * 0.06 + out_px, (H - frame_h) / 2 + out_px / 2))
        fy = min(fy, H - frame_h - int(H * 0.05))
        oy = fy - cut * s
    else:
        fy = int(max(H * 0.06, (H - frame_h - out_px) / 2))
        oy = fy + frame_h - cut * s
    fx = (W - frame_w) // 2
    sw, sh = pw * s, ph * s
    ox = fx + frame_w / 2 - (bx0 + bx1) / 2 * s
    ox = min(ox, fx)
    if ox + sw < fx + frame_w:
        ox = fx + frame_w - sw
    oy = min(oy, fy)
    if oy + sh < fy + frame_h:
        oy = fy + frame_h - sh
    return {"variant": variant, "frame": (fx, fy, frame_w, frame_h), "scale": s, "offset": (ox, oy),
            "W": W, "H": H, "fade_bottom": variant == "bottom" and by1 >= ph * 0.97}


def layers(photo: np.ndarray, mask: np.ndarray, lay: dict, bg_kind: str = "paper", border: int = 0):
    """Background, frame layer (photo window + shadow) and the cut-out subject, all canvas-sized."""
    W, H = lay["W"], lay["H"]
    s = lay["scale"]
    ox, oy = lay["offset"]
    M = np.array([[s, 0, ox], [0, s, oy]], np.float32)
    big = cv2.warpAffine(photo, M, (W, H), flags=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC,
                         borderMode=cv2.BORDER_REFLECT)
    m = cv2.warpAffine(mask, M, (W, H), flags=cv2.INTER_LINEAR, borderValue=0)
    m = np.clip((m - 0.08) / 0.84, 0, 1)  # firm up the matte edge a little
    if lay.get("fade_bottom"):  # subject cut by the photo edge: fade it out instead of a hard line
        bottom = int(min(H, oy + photo.shape[0] * s))
        span = int(0.06 * H)
        ramp = np.ones(H, np.float32)
        ramp[max(0, bottom - span):bottom] = np.linspace(1, 0, min(span, bottom))
        ramp[bottom:] = 0
        m = m * ramp[:, None]
    bg = background(bg_kind, W, H, photo)
    fx, fy, fw, fh = lay["frame"]
    frame_a = np.zeros((H, W), np.float32)
    frame_a[fy:fy + fh, fx:fx + fw] = 1
    if border:
        frame_a2 = np.zeros((H, W), np.float32)
        frame_a2[fy - border:fy + fh + border, fx - border:fx + fw + border] = 1
    else:
        frame_a2 = frame_a
    return {"bg": bg, "photo": big, "frame_a": frame_a, "border_a": frame_a2, "subject_a": m}


def compose(L: dict, t_frame: float = 1.0, t_subject: float = 1.0, zoom: float = 1.0) -> np.ndarray:
    """Final image. t_frame / t_subject 0..1 animate the frame and the pop-out entering."""
    bg, photo = L["bg"].astype(np.float32), L["photo"].astype(np.float32)
    H, W = bg.shape[:2]
    fa, ba, sa = L["frame_a"], L["border_a"], L["subject_a"]
    if t_frame < 1:
        k = 0.9 + 0.1 * t_frame
        Ms = cv2.getRotationMatrix2D((W / 2, H / 2), 0, k)
        fa = cv2.warpAffine(fa, Ms, (W, H)) * t_frame
        ba = cv2.warpAffine(ba, Ms, (W, H)) * t_frame
    sa_out = sa * (1 - fa)  # the parts of the subject outside the frame
    if t_subject < 1:
        sa_out = sa_out * t_subject
    out = bg
    # soft drop shadows under the frame and the popped-out subject: depth
    shadow = cv2.GaussianBlur(np.maximum(ba, sa_out), (0, 0), 18)
    shadow = np.roll(shadow, (14, 6), axis=(0, 1)) * 0.38
    out = out * (1 - shadow[..., None])
    if ba is not fa:  # white print border
        out = out * (1 - ba[..., None]) + 250 * ba[..., None]
    out = out * (1 - fa[..., None]) + photo * fa[..., None]
    out = out * (1 - sa_out[..., None]) + photo * sa_out[..., None]
    out = np.clip(out, 0, 255).astype(np.uint8)
    if zoom != 1.0:
        Mz = cv2.getRotationMatrix2D((W / 2, H / 2), 0, zoom)
        out = cv2.warpAffine(out, Mz, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    return out


def load_photo(path: Path, max_side: int = 2600) -> tuple[np.ndarray, str]:
    from PIL import ImageOps
    try:
        import pillow_heif  # noqa: F401
        pillow_heif.register_heif_opener()
    except Exception:
        pass
    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    if max(im.size) > max_side:
        im.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    st = path.stat()
    key = hashlib.sha1(f"{path.resolve()}|{st.st_size}|{int(st.st_mtime)}|{im.size}".encode()).hexdigest()[:16]
    return np.asarray(im), key


def make_still(path: Path, out: Path, fmt: str = "post", bg: str = "paper", variant: str = "auto",
               border: int = 0, model: str = "isnet-general-use", look: str | None = None,
               strength: float = 0.8) -> Path:
    photo, key = load_photo(path)
    m = subject_mask(photo, key, model)
    ok, why = usable(m)
    if not ok:
        raise ReelError(f"{path.name}: {why}, so there's nothing to pop out of the frame")
    if look and look not in ("none", "off"):
        from . import grade
        photo = grade.grade_image(photo, look, strength)
    W, H = FORMATS[fmt]
    lay = plan_layout(photo.shape, mask_box(m), W, H, variant)
    img = compose(layers(photo, m, lay, bg, border))
    out.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(img).save(out, quality=95)
    return out


def animate_frames(path: str, n: int, fps: int, W: int = 1080, H: int = 1920, bg: str = "paper",
                   variant: str = "auto", border: int = 0, lut: str | None = None):
    """Frames for a reel shot: the frame settles in, then the subject steps out of it on the beat,
    with a slow push-in. Returns None when the photo has no clear subject."""
    photo, key = load_photo(Path(path))
    m = subject_mask(photo, key)
    ok, _ = usable(m)
    if not ok:
        return None
    if lut:  # grade the photo only, so the paper/frame stays clean
        from .grade import apply_cube
        photo = apply_cube(photo, Path(lut))
    L = layers(photo, m, plan_layout(photo.shape, mask_box(m), W, H, variant), bg, border)

    def gen():
        for k in range(n):
            t = k / fps
            tf = min(1.0, t / 0.3)
            tf = 1 - (1 - tf) ** 3
            q = min(1.0, max(0.0, (t - 0.25) / 0.25))
            ts = 1 - (1 - q) ** 3
            yield compose(L, tf, ts, zoom=1.0 + 0.04 * k / max(1, n - 1))
    return gen()
