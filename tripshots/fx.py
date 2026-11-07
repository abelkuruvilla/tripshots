"""Reusable ffmpeg filter snippets."""
from __future__ import annotations

from pathlib import Path

from .util import has_filter, log

_warned_hdr = False


def hdr_chain(info: dict) -> list[str]:
    """Tone-map iPhone/Android HDR (HLG/PQ) to SDR so footage doesn't look washed out."""
    global _warned_hdr
    if not info.get("hdr"):
        return []
    if has_filter("zscale") and has_filter("tonemap"):
        if info.get("transfer") == "smpte2084":  # HDR10 / Dolby Vision (PQ)
            npl, tm = 100, "tonemap=hable:desat=0"
        else:  # HLG (iPhone default): reference white is 203 nits; mobius keeps mid-tones natural
            npl, tm = 203, "tonemap=mobius:param=0.3:desat=0"
        return [f"zscale=t=linear:npl={npl}", "format=gbrpf32le", "zscale=p=bt709",
                tm, "zscale=t=bt709:m=bt709:r=tv"]
    if not _warned_hdr:
        log("HDR footage found but this ffmpeg lacks zscale; colors may look flat "
            "(macOS: `brew install ffmpeg` includes it)")
        _warned_hdr = True
    return []


def color_chain(color: dict) -> list[str]:
    f: list[str] = []
    sat = float(color.get("saturation", 1.0))
    con = float(color.get("contrast", 1.0))
    bri = float(color.get("brightness", 0.0))
    gam = float(color.get("gamma", 1.0))
    if (sat, con, bri, gam) != (1.0, 1.0, 0.0, 1.0):
        f.append(f"eq=saturation={sat:.3f}:contrast={con:.3f}:brightness={bri:.3f}:gamma={gam:.3f}")
    warm = float(color.get("warmth", 0.0))
    if abs(warm) > 1e-3:
        w = max(-0.3, min(0.3, warm))
        f.append(f"colorbalance=rm={w:.3f}:bm={-w:.3f}:rh={w / 2:.3f}:bh={-w / 2:.3f}")
    lut = color.get("lut")
    if lut and Path(str(lut)).expanduser().exists():
        f.append(f"lut3d=file='{Path(str(lut)).expanduser()}'")
    sh = float(color.get("sharpen", 0.0) or 0.0)
    if sh > 0:
        f.append(f"unsharp=5:5:{min(sh, 1.5):.2f}:5:5:0")
    if color.get("vignette"):
        f.append("vignette=angle=PI/5")
    g = int(color.get("grain") or 0)
    if g:
        f.append(f"noise=c0s={min(g, 12)}:c0f=t+u")
    return f


def seg_color(color: dict, e: dict) -> dict:
    """Colour settings for one shot. With a per-shot grading LUT (`e["lut"]`, see grade.py) the
    LUT replaces the style's global saturation/contrast/warmth and the look adds its finishing."""
    lut = e.get("lut")
    if not lut or not Path(str(lut)).exists():
        return color
    g = color.get("grade") or {}
    return {"lut": lut, "sharpen": color.get("sharpen", 0.0),
            "vignette": bool(g.get("vignette")) or bool(color.get("vignette")), "grain": g.get("grain", 0)}
