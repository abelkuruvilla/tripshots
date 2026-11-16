"""Flat "log" footage (Apple Log, DJI D-Log, Sony S-Log3, Panasonic V-Log, Fujifilm F-Log/F-Log2, Canon C-Log3)
turned into normal-looking video before anything else colours it.

Each camera's log curve is its maker's published formula (code value -> scene light). The light is then taken
into Rec.709 colours (a 3x3 matrix from the camera's colour space; where we don't have the maker's matrix,
Rec.2020's is used as the nearest wide gamut), and shown with a soft filmic roll-off (highlights compress, mid
grey lands where a normal video puts it). The result is a 33-point .cube in ~/.tripshots/luts/camlog/, applied
with ffmpeg's lut3d right after the HDR tone-map (render) and to thumbnails for grading (grade.shot_stats).

Segment / shot field `log`: a profile id. `mark` sets it automatically only when the camera is one that films
log AND the clip looks flat; anything else is set by hand (planedit `log`, the editor's Colour tab).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .config import HOME

CACHE = HOME / "luts" / "camlog"
SIZE = 33


def _slog3(x):
    return np.where(x >= 171.2102946929 / 1023, 10 ** ((x * 1023 - 420) / 261.5) * 0.19 - 0.01,
                    (x * 1023 - 95) * 0.01125 / (171.2102946929 - 95))


def _vlog(x):
    return np.where(x < 0.181, (x - 0.125) / 5.6, 10 ** ((x - 0.598206) / 0.241514) - 0.00873)


def _flog(x):
    return np.where(x >= 0.100537775223865, (10 ** ((x - 0.790453) / 0.344676) - 0.009468) / 0.555556,
                    (x - 0.092864) / 8.735631)


def _flog2(x):
    return np.where(x >= 0.100686685370811, (10 ** ((x - 0.384316) / 0.245281) - 0.064829) / 5.555556,
                    (x - 0.092864) / 8.799461)


def _clog3(x):
    return np.where(x < 0.097465473, -(10 ** ((0.12783901 - x) / 0.36726845) - 1) / 14.98325,
                    np.where(x <= 0.15277891, (x - 0.12512219) / 1.9754798,
                             (10 ** ((x - 0.12240537) / 0.36726845) - 1) / 14.98325))


def _apple(x):
    r0, rt, c, b, g, be = -0.05641088, 0.01, 47.28711236, 0.00964052, 0.08550479, 0.69336945
    pt = c * (rt - r0) ** 2
    return np.where(x >= pt, 2 ** ((x - be) / g) - b, np.where(x >= 0, np.sqrt(np.maximum(x, 0) / c) + r0, r0))


def _dlog(x):
    return np.where(x <= 0.14, (x - 0.0929) / 6.025, (10 ** (3.89616 * x - 2.27752) - 0.0108) / 0.9892)


REC2020 = np.array([[1.6605, -0.5876, -0.0728], [-0.1246, 1.1329, -0.0083], [-0.0182, -0.1006, 1.1187]])
SGAMUT3_CINE = np.array([[1.6269474, -0.5401385, -0.0868089], [-0.1785155, 1.4179409, -0.2394254],
                         [-0.0444361, -0.1959199, 1.2403560]])
VGAMUT = np.array([[1.806576, -0.695697, -0.110879], [-0.170090, 1.305955, -0.135865],
                   [-0.025206, -0.154468, 1.179674]])

# id: (name, curve, matrix to Rec.709, camera makes it is the usual log of)
PROFILES = {
    "apple_log": ("Apple Log", _apple, REC2020, ("apple",)),
    "dlog": ("DJI D-Log", _dlog, REC2020, ("dji",)),
    "slog3": ("Sony S-Log3", _slog3, SGAMUT3_CINE, ("sony",)),
    "vlog": ("Panasonic V-Log", _vlog, VGAMUT, ("panasonic",)),
    "flog": ("Fujifilm F-Log", _flog, REC2020, ("fujifilm", "fuji")),
    "flog2": ("Fujifilm F-Log2", _flog2, REC2020, ()),
    "clog3": ("Canon C-Log3", _clog3, REC2020, ("canon",)),
}


def _display(lin: np.ndarray) -> np.ndarray:
    """Scene light -> a normal video picture: a filmic curve (mid grey near 0.41 on screen), then the sRGB/709 encode."""
    x = np.maximum(lin, 0) * 0.6
    y = np.clip(x * (2.51 * x + 0.03) / (x * (2.43 * x + 0.59) + 0.14), 0, 1)
    return np.where(y <= 0.0031308, 12.92 * y, 1.055 * np.power(y, 1 / 2.4) - 0.055)


def convert(rgb01: np.ndarray, profile: str) -> np.ndarray:
    """Float RGB 0..1 (log footage) -> float RGB 0..1 (normal video)."""
    _, curve, m, _ = PROFILES[profile]
    lin = curve(np.asarray(rgb01, np.float64))
    lin = lin @ m.T
    return np.clip(_display(lin), 0, 1)


def convert_rgb8(img: np.ndarray, profile: str) -> np.ndarray:
    return (convert(img.astype(np.float64) / 255.0, profile) * 255 + 0.5).astype(np.uint8)


def cube(profile: str) -> Path:
    """The profile as a .cube 3D LUT (written once)."""
    out = CACHE / f"{profile}_v1.cube"
    if out.exists():
        return out
    CACHE.mkdir(parents=True, exist_ok=True)
    g = np.linspace(0, 1, SIZE)
    b, gg, r = np.meshgrid(g, g, g, indexing="ij")          # .cube order: red changes fastest
    rgb = np.stack([r, gg, b], -1).reshape(-1, 3)
    vals = convert(rgb, profile)
    lines = [f'TITLE "{PROFILES[profile][0]} to Rec.709 (TripShots)"', f"LUT_3D_SIZE {SIZE}"]
    lines += [f"{v[0]:.6f} {v[1]:.6f} {v[2]:.6f}" for v in vals]
    tmp = out.with_suffix(".part")
    tmp.write_text("\n".join(lines) + "\n")
    tmp.replace(out)
    return out


def chain(e: dict) -> list[str]:
    """ffmpeg filters for a shot's log conversion (none when it isn't log)."""
    p = e.get("log")
    if p not in PROFILES:
        return []
    return [f"lut3d=file='{cube(p)}'"]


# ---------------------------------------------------------------- detection
_makes: dict[str, str] = {}


def camera(src: str) -> str:
    """The camera maker from a file's metadata ('' when it doesn't say)."""
    if src in _makes:
        return _makes[src]
    make = ""
    try:
        from .util import ffprobe
        info = ffprobe(Path(src))
        tags = {k.lower(): str(v).lower() for s in [info.get("format") or {}] + list(info.get("streams") or [])
                for k, v in (s.get("tags") or {}).items()}
        blob = " ".join(tags.values())
        for k in ("com.apple.quicktime.make", "make", "com.android.manufacturer"):
            if tags.get(k):
                make = tags[k]
                break
        for name in ("dji", "sony", "panasonic", "fujifilm", "canon", "apple", "insta360", "gopro"):
            if not make and name in blob:
                make = name
    except Exception:
        make = ""
    _makes[src] = make
    return make


def looks_flat(img: np.ndarray) -> bool:
    """A picture with log's tell-tale look: lifted blacks, no bright whites and washed-out colour."""
    import cv2
    g = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY).astype(np.float32) / 255.0
    p2, p98 = np.percentile(g, 2), np.percentile(g, 98)
    sat = cv2.cvtColor(img, cv2.COLOR_RGB2HSV)[..., 1].mean() / 255.0
    return bool(p2 > 0.06 and p98 - p2 < 0.62 and p98 < 0.86 and sat < 0.24)


def detect(shot: dict) -> str | None:
    """The shot's log profile, when its camera films log and the clip looks flat; else None."""
    if shot.get("kind") != "video" or shot.get("hdr"):
        return None
    make = camera(str(shot.get("src") or ""))
    prof = next((k for k, v in PROFILES.items() if any(m in make for m in v[3])), None)
    if not prof:
        return None
    import cv2
    im = cv2.imread(str(shot.get("thumb") or ""))
    if im is None:
        return None
    return prof if looks_flat(cv2.cvtColor(im, cv2.COLOR_BGR2RGB)) else None


def mark(plan: dict, by_id: dict) -> list[str]:
    """Set `log` on log shots (shot records and their segments) unless already decided; returns what was found."""
    found = []
    for seg in plan.get("segments") or []:
        for c in (seg.get("clips") or [seg]):
            sh = by_id.get(c.get("shot_id"))
            if not sh or "log" in c:
                continue
            if "log" not in sh:
                sh["log"] = detect(sh)
            if sh["log"]:
                c["log"] = sh["log"]
                found.append(f"{c['shot_id']}: {PROFILES[sh['log']][0]}")
    return found
