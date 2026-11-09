"""Fonts for text that isn't in the Latin alphabet (Malayalam, Hindi, Tamil, Arabic, Japanese...).

The bundled display fonts only cover Latin (and some Cyrillic). When a line is in another script, typo.py draws
it with a font for that script, shaped properly (Pillow's Raqm layout: conjuncts, vowel signs, right to left):
  1. ~/.tripshots/fonts/ (fonts fetched earlier, or your own: drop a .ttf/.otf there)
  2. a font of the computer (macOS: Malayalam Sangam MN, Kohinoor, PingFang...; Linux: Noto)
  3. Noto Sans for that script, fetched once from the Fontsource package on jsDelivr (SIL Open Font License)
"""
from __future__ import annotations

import glob
import os
import urllib.request
from pathlib import Path

from .config import HOME
from .util import log

FONT_HOME = HOME / "fonts"
# script -> (unicode ranges, fontsource family, fontsource subset, words to look for in system font names)
SCRIPTS = {
    "malayalam": ([(0x0D00, 0x0D7F)], "noto-sans-malayalam", "malayalam", ["Malayalam"]),
    "devanagari": ([(0x0900, 0x097F), (0xA8E0, 0xA8FF)], "noto-sans-devanagari", "devanagari",
                   ["Devanagari", "Kohinoor.ttc", "Mukta"]),
    "tamil": ([(0x0B80, 0x0BFF)], "noto-sans-tamil", "tamil", ["Tamil"]),
    "telugu": ([(0x0C00, 0x0C7F)], "noto-sans-telugu", "telugu", ["Telugu"]),
    "kannada": ([(0x0C80, 0x0CFF)], "noto-sans-kannada", "kannada", ["Kannada"]),
    "bengali": ([(0x0980, 0x09FF)], "noto-sans-bengali", "bengali", ["Bangla", "Bengali"]),
    "gujarati": ([(0x0A80, 0x0AFF)], "noto-sans-gujarati", "gujarati", ["Gujarati"]),
    "gurmukhi": ([(0x0A00, 0x0A7F)], "noto-sans-gurmukhi", "gurmukhi", ["Gurmukhi"]),
    "arabic": ([(0x0600, 0x06FF), (0x0750, 0x077F), (0xFB50, 0xFDFF), (0xFE70, 0xFEFF)], "noto-sans-arabic",
               "arabic", ["Arabic", "GeezaPro", "Geeza Pro"]),
    "hebrew": ([(0x0590, 0x05FF)], "noto-sans-hebrew", "hebrew", ["Hebrew", "ArialHB"]),
    "thai": ([(0x0E00, 0x0E7F)], "noto-sans-thai", "thai", ["Thai", "Thonburi"]),
    "greek": ([(0x0370, 0x03FF)], "noto-sans", "greek", ["NotoSans-", "Helvetica"]),
    "cjk": ([(0x3040, 0x30FF), (0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xAC00, 0xD7AF), (0xFF00, 0xFFEF)], None, None,
            ["PingFang", "Hiragino Sans", "AppleSDGothicNeo", "NotoSansCJK", "NotoSansJP", "NotoSansSC",
             "NotoSansKR", "Arial Unicode"]),
}
SYSTEM_DIRS = ["/System/Library/Fonts", "/System/Library/Fonts/Supplemental", "/Library/Fonts",
               str(Path.home() / "Library/Fonts"), "/usr/share/fonts", "/usr/local/share/fonts",
               str(Path.home() / ".local/share/fonts"), "C:/Windows/Fonts"]
CDN = "https://cdn.jsdelivr.net/npm/@fontsource/{fam}@5/files/{fam}-{sub}-{w}-normal.woff"
_found: dict = {}


def script_of(text: str) -> str | None:
    """The first non-Latin script in the text (None for Latin, Cyrillic, digits and punctuation)."""
    for ch in text or "":
        o = ord(ch)
        if o < 0x0370:
            continue
        for name, (ranges, *_rest) in SCRIPTS.items():
            if any(a <= o <= b for a, b in ranges):
                return name
    return None


def _system(words: list[str]) -> Path | None:
    for d in SYSTEM_DIRS:
        if not Path(d).is_dir():
            continue
        for w in words:
            hits = sorted(glob.glob(f"{d}/**/*{w}*", recursive=True))
            hits = [h for h in hits if h.lower().endswith((".ttf", ".otf", ".ttc"))]
            bold = [h for h in hits if "bold" in Path(h).name.lower()]
            if bold or hits:
                return Path((bold or hits)[0])
    return None


def font_for(script: str, weight: int = 700) -> Path | None:
    """A font file that covers the script (cached per run)."""
    if script in _found:
        return _found[script]
    _ranges, fam, sub, words = SCRIPTS[script]
    got = None
    own = sorted(FONT_HOME.glob(f"*{script}*")) + (sorted(FONT_HOME.glob(f"{fam}-{sub}-*")) if fam else [])
    if own:
        got = own[0]
    if got is None:
        got = _system(words)
    if got is None and fam and os.environ.get("TRIPSHOTS_OFFLINE") != "1":
        dest = FONT_HOME / f"{fam}-{sub}-{weight}-normal.woff"
        url = CDN.format(fam=fam, sub=sub, w=weight)
        try:
            FONT_HOME.mkdir(parents=True, exist_ok=True)
            req = urllib.request.Request(url, headers={"User-Agent": "tripshots (fonts)"})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
            if len(data) > 1000:
                dest.write_bytes(data)
                got = dest
                log(f"fonts: fetched Noto Sans for {script} text (SIL OFL) into {FONT_HOME}")
        except Exception as e:
            log(f"fonts: no font for {script} text ({str(e)[:80]}); put a .ttf in {FONT_HOME}")
    _found[script] = got
    return got


def for_text(text: str) -> Path | None:
    """A font for the text's script, or None when the bundled fonts cover it."""
    sc = script_of(text)
    return font_for(sc) if sc else None
