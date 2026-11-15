"""Reusable ffmpeg filter snippets."""
from __future__ import annotations

from pathlib import Path

from .util import has_filter, log

_warned_hdr = False


def zscale_chain(transfer: str | None) -> list[str]:
    """HDR -> SDR with zscale + tonemap (tools/make_hdr_luts.py measures this into the fallback tables)."""
    if transfer == "smpte2084":  # HDR10 / Dolby Vision (PQ)
        npl, tm = 100, "tonemap=hable:desat=0"
    else:  # HLG (iPhone default): reference white is 203 nits; mobius keeps mid-tones natural
        npl, tm = 203, "tonemap=mobius:param=0.3:desat=0"
    return [f"zscale=t=linear:npl={npl}", "format=gbrpf32le", "zscale=p=bt709",
            tm, "zscale=t=bt709:m=bt709:r=tv"]


def hdr_chain(info: dict) -> list[str]:
    """Tone-map iPhone/Android HDR (HLG/PQ) to SDR so footage doesn't look washed out."""
    global _warned_hdr
    if not info.get("hdr"):
        return []
    if has_filter("zscale") and has_filter("tonemap"):
        return zscale_chain(info.get("transfer"))
    if has_filter("lut3d"):  # no zscale (Homebrew's standard ffmpeg): the same maths as a LUT (hdrlut.py)
        from .hdrlut import chain
        return chain(info)
    if not _warned_hdr:
        log("HDR footage found but this ffmpeg has neither zscale nor lut3d; colours may look flat")
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
    f += adjust_chain(color.get("adjust"))
    sh = float(color.get("sharpen", 0.0) or 0.0)
    if sh > 0:
        f.append(f"unsharp=5:5:{min(sh, 1.5):.2f}:5:5:0")
    if color.get("vignette"):
        f.append("vignette=angle=PI/5")
    g = int(color.get("grain") or 0)
    if g:
        f.append(f"noise=c0s={min(g, 12)}:c0f=t+u")
    return f


ADJUST = {  # a shot's own corrections in the editor, on top of the grade: (low, high, neutral)
    "exposure": (-2.0, 2.0, 0.0),     # stops
    "contrast": (0.4, 1.6, 1.0),
    "saturation": (0.0, 2.0, 1.0),
    "warmth": (-1.0, 1.0, 0.0),       # cool .. warm
    "tint": (-1.0, 1.0, 0.0),         # green .. magenta
    "shadows": (-1.0, 1.0, 0.0),      # crush .. lift
    "highlights": (-1.0, 1.0, 0.0),   # recover .. brighten
}


def adjust_chain(adj: dict | None) -> list[str]:
    """ffmpeg filters for a shot's own corrections (segment `adjust`), applied after its grading LUT."""
    if not adj:
        return []
    v = {k: float(adj.get(k, n)) for k, (_lo, _hi, n) in ADJUST.items()}
    f = []
    if v["exposure"]:
        f.append(f"exposure=exposure={max(-2.0, min(2.0, v['exposure'])):.3f}")
    if v["shadows"] or v["highlights"]:
        s, h = 0.25 * v["shadows"], 0.18 * v["highlights"]
        pts = f"0/{max(0.0, s * 0.4):.3f} 0.25/{0.25 + s:.3f} 0.75/{0.75 + h:.3f} 1/{min(1.0, 1 + h * 0.3):.3f}"
        f.append(f"curves=all='{pts}'")
    if (v["contrast"], v["saturation"]) != (1.0, 1.0):
        f.append(f"eq=contrast={v['contrast']:.3f}:saturation={v['saturation']:.3f}")
    w, t = 0.25 * v["warmth"], 0.2 * v["tint"]
    if w or t:
        f.append(f"colorbalance=rm={w:.3f}:gm={-t:.3f}:bm={-w:.3f}:rh={w / 2:.3f}:gh={-t / 2:.3f}:bh={-w / 2:.3f}")
    return f


def seg_color(color: dict, e: dict) -> dict:
    """Colour settings for one shot. With a per-shot grading LUT (`e["lut"]`, see grade.py) the
    LUT replaces the style's global saturation/contrast/warmth and the look adds its finishing.
    `no_grade` shows the shot as filmed (the style's light touch only); `adjust` is the editor's own
    corrections on top (adjust_chain)."""
    lut = None if e.get("no_grade") else e.get("lut")
    adj = e.get("adjust") or None
    if not lut or not Path(str(lut)).exists():
        out = {k: v for k, v in color.items() if k != "lut"} if e.get("no_grade") else color
        return {**out, "adjust": adj} if adj else out
    g = color.get("grade") or {}
    return {"lut": lut, "sharpen": color.get("sharpen", 0.0), "adjust": adj,
            "vignette": bool(g.get("vignette")) or bool(color.get("vignette")), "grain": g.get("grain", 0)}
