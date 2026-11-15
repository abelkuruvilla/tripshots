"""A library of open fonts for on-screen text, fetched once from Google Fonts (SIL OFL / Apache) into
~/.tripshots/fonts/gf. The bundled faces cover a few looks; reference reels use many more (a Times-like serif
for quiet lyrics, a thin Malayalam face, a heavy grotesque for a magazine title...), so reftext.match_font can
pick the closest of these to what a reference shows.

A font is named "gf:Family:weight" (e.g. "gf:Tinos:400") wherever a style or plan names a font; typo.font loads
it through here. `TRIPSHOTS_OFFLINE=1` never downloads: an unfetched font falls back to the bundled sans.
"""
from __future__ import annotations

import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

from .config import HOME
from .util import log

DIR = HOME / "fonts" / "gf"
API = "https://fonts.googleapis.com/css2?family={fam}:wght@{w}"
UA = "Mozilla/4.0 (tripshots fonts)"  # an old browser is sent plain TrueType files

# family -> (look, weights, scripts). look: sans, rounded, grotesque, condensed, serif, script, hand, mono, display
CATALOG: dict[str, tuple[str, tuple, tuple]] = {
    "Inter": ("sans", (300, 400, 600, 800), ("latin",)),
    "Poppins": ("sans", (300, 400, 600, 800), ("latin",)),
    "DM Sans": ("sans", (300, 400, 700), ("latin",)),
    "Montserrat": ("sans", (300, 500, 800), ("latin",)),
    "Nunito": ("rounded", (400, 700, 900), ("latin",)),
    "Quicksand": ("rounded", (500, 700), ("latin",)),
    "Varela Round": ("rounded", (400,), ("latin",)),
    "Fredoka": ("rounded", (400, 600), ("latin",)),
    "Comfortaa": ("rounded", (400, 700), ("latin",)),
    "Raleway": ("sans", (300, 600, 800), ("latin",)),
    "Josefin Sans": ("sans", (300, 600), ("latin",)),
    "Work Sans": ("sans", (400, 700), ("latin",)),
    "Outfit": ("sans", (300, 600, 800), ("latin",)),
    "Sora": ("sans", (400, 700), ("latin",)),
    "Archivo": ("grotesque", (400, 700, 900), ("latin",)),
    "Archivo Narrow": ("condensed", (400, 700), ("latin",)),
    "Oswald": ("condensed", (300, 500, 700), ("latin",)),
    "Anton": ("condensed", (400,), ("latin",)),
    "Bebas Neue": ("condensed", (400,), ("latin",)),
    "League Gothic": ("condensed", (400,), ("latin",)),
    "Tinos": ("serif", (400, 700), ("latin",)),             # Times New Roman's shapes
    "Cormorant Garamond": ("serif", (300, 500, 700), ("latin",)),
    "EB Garamond": ("serif", (400, 600), ("latin",)),
    "Playfair Display": ("serif", (400, 700, 900), ("latin",)),
    "Lora": ("serif", (400, 700), ("latin",)),
    "Libre Baskerville": ("serif", (400, 700), ("latin",)),
    "Gelasio": ("serif", (400, 700), ("latin",)),          # Georgia's shapes
    "Bodoni Moda": ("serif", (400, 700), ("latin",)),
    "Cinzel": ("serif", (400, 700), ("latin",)),
    "DM Serif Display": ("serif", (400,), ("latin",)),
    "Abril Fatface": ("display", (400,), ("latin",)),
    "Alfa Slab One": ("display", (400,), ("latin",)),
    "Rye": ("display", (400,), ("latin",)),
    "Bungee": ("display", (400,), ("latin",)),
    "Lobster": ("script", (400,), ("latin",)),
    "Great Vibes": ("script", (400,), ("latin",)),
    "Dancing Script": ("script", (400, 700), ("latin",)),
    "Pacifico": ("script", (400,), ("latin",)),
    "Sacramento": ("script", (400,), ("latin",)),
    "Yellowtail": ("script", (400,), ("latin",)),
    "Caveat": ("hand", (400, 700), ("latin",)),
    "Kalam": ("hand", (300, 700), ("latin",)),
    "Permanent Marker": ("hand", (400,), ("latin",)),
    "Courier Prime": ("mono", (400, 700), ("latin",)),
    "Special Elite": ("mono", (400,), ("latin",)),
    "Manjari": ("sans", (100, 400, 700), ("malayalam", "latin")),
    "Noto Sans Malayalam": ("sans", (300, 500, 800), ("malayalam",)),
    "Noto Serif Malayalam": ("serif", (400, 700), ("malayalam",)),
    "Anek Malayalam": ("condensed", (400, 700), ("malayalam",)),
    "Baloo Chettan 2": ("display", (500, 800), ("malayalam", "latin")),
    "Gayathri": ("sans", (100, 400, 700), ("malayalam", "latin")),
    "Chilanka": ("hand", (400,), ("malayalam", "latin")),
    "Noto Sans Tamil": ("sans", (300, 500, 800), ("tamil",)),
    "Noto Sans Devanagari": ("sans", (300, 500, 800), ("devanagari",)),
}
_failed: set = set()


def name(family: str, weight: int) -> str:
    return f"gf:{family}:{int(weight)}"


def parse(spec: str) -> tuple[str, int] | None:
    m = re.fullmatch(r"gf:([^:]+):(\d+)", str(spec or "").strip())
    return (m.group(1), int(m.group(2))) if m else None


def path(family: str, weight: int) -> Path:
    return DIR / f"{family.replace(' ', '')}-{int(weight)}.ttf"


def get(family: str, weight: int) -> Path | None:
    """The font file for the family at that weight, fetched once. None when it can't be had."""
    p = path(family, weight)
    if p.exists() and p.stat().st_size > 1000:
        return p
    key = (family, int(weight))
    if key in _failed or os.environ.get("TRIPSHOTS_OFFLINE") == "1":
        return None
    try:
        url = API.format(fam=urllib.parse.quote(family), w=int(weight))
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            css = r.read().decode("utf-8", "replace")
        srcs = re.findall(r"url\((https://fonts\.gstatic\.com/[^)]+\.ttf)\)", css)
        if not srcs:
            raise ValueError("no TrueType file offered")
        with urllib.request.urlopen(urllib.request.Request(srcs[-1], headers={"User-Agent": UA}), timeout=60) as r:
            data = r.read()
        if len(data) < 1000:
            raise ValueError("empty file")
        DIR.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return p
    except Exception as e:
        _failed.add(key)
        log(f"fonts: couldn't fetch {family} {weight} ({str(e)[:80]})")
        return None


def candidates(script: str = "latin") -> list[tuple[str, int]]:
    """Every (family, weight) that can set text in the script."""
    return [(fam, w) for fam, (_look, weights, scripts) in CATALOG.items() if script in scripts for w in weights]


def look_of(family: str) -> str:
    return CATALOG.get(family, ("sans",))[0]
