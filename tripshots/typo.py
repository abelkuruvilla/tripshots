"""Animated typography, composited frame by frame.

Text is laid out once into small RGBA sprites (one per word, line or character,
depending on the animation), then animated per frame (scale, offset, alpha, mask
reveal) and alpha-blended onto the video. Words can land on the beat.

Presets (style text.preset) pick fonts and animations that work together:
  bold        Anton caps, words pop in on the beat; title card location
  editorial   Playfair italic, lines slide up from a mask; serif title card
  minimal     Montserrat, letter-spacing opens up; small tracked location
  handwritten Permanent Marker, scale-in; marker location
  typewriter  Space Mono, typed letter by letter; mono location
Fonts are bundled (SIL Open Font License / Apache 2.0), see tripshots/fonts/.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .config import CANVAS

FONT_DIR = Path(__file__).parent / "fonts"
FONTS = {  # name -> (file, variable weight or None)
    "anton": ("Anton-Regular.ttf", None),
    "bebas": ("BebasNeue-Regular.ttf", None),
    "archivo": ("ArchivoBlack-Regular.ttf", None),
    "montserrat": ("Montserrat.ttf", 600),
    "montserrat-light": ("Montserrat.ttf", 300),
    "montserrat-bold": ("Montserrat.ttf", 800),
    "playfair": ("PlayfairDisplay.ttf", 700),
    "playfair-italic": ("PlayfairDisplay-Italic.ttf", 600),
    "dmserif": ("DMSerifDisplay-Regular.ttf", None),
    "dmserif-italic": ("DMSerifDisplay-Italic.ttf", None),
    "spacemono": ("SpaceMono-Regular.ttf", None),
    "spacemono-bold": ("SpaceMono-Bold.ttf", None),
    "marker": ("PermanentMarker-Regular.ttf", None),
    "caveat": ("Caveat.ttf", 700),
}

PRESETS = {
    "bold": {
        "hook": {"font": "anton", "size": 118, "anim": "pop", "uppercase": True, "line_gap": 0.98},
        "location": {"anim": "slide", "layout": "title", "font": "bebas", "size": 150, "behind": "auto",
                     "behind_font": "anton",
                     "sub_font": "montserrat", "sub_size": 38, "mono_font": "spacemono", "mono_size": 30},
        "cta": {"font": "montserrat-bold", "size": 58, "anim": "slide"},
        "label": {"font": "anton", "size": 92, "anim": "pop", "uppercase": True, "position": "lower"},
    },
    "editorial": {
        "hook": {"font": "playfair-italic", "size": 92, "anim": "slide", "uppercase": False, "line_gap": 1.08},
        "location": {"anim": "slide", "layout": "title", "font": "dmserif", "size": 120, "behind": "auto",
                     "behind_font": "dmserif",
                     "sub_font": "montserrat-light", "sub_size": 38, "mono_font": "spacemono", "mono_size": 28},
        "cta": {"font": "playfair-italic", "size": 64, "anim": "slide"},
        "label": {"font": "playfair-italic", "size": 76, "anim": "slide", "position": "lower"},
    },
    "minimal": {
        "hook": {"font": "montserrat", "size": 64, "anim": "tracking", "uppercase": True, "line_gap": 1.2},
        "location": {"anim": "tracking", "layout": "line", "font": "montserrat", "size": 40, "behind": "off",
                     "mono_font": "spacemono", "mono_size": 28},
        "cta": {"font": "montserrat", "size": 48, "anim": "tracking"},
        "label": {"font": "montserrat", "size": 46, "anim": "tracking", "uppercase": True, "position": "lower"},
    },
    "handwritten": {
        "hook": {"font": "marker", "size": 100, "anim": "scale", "uppercase": False, "line_gap": 1.05},
        "location": {"anim": "scale", "layout": "title", "font": "marker", "size": 110, "behind": "auto",
                     "behind_font": "marker",
                     "sub_font": "caveat", "sub_size": 60, "mono_font": "spacemono", "mono_size": 28},
        "cta": {"font": "caveat", "size": 76, "anim": "scale"},
        "label": {"font": "marker", "size": 78, "anim": "scale", "position": "lower"},
    },
    "typewriter": {
        "hook": {"font": "spacemono-bold", "size": 66, "anim": "typewriter", "uppercase": False, "line_gap": 1.25},
        "location": {"anim": "typewriter", "layout": "line", "font": "spacemono-bold", "size": 42, "behind": "off",
                     "mono_font": "spacemono", "mono_size": 28},
        "cta": {"font": "spacemono", "size": 46, "anim": "typewriter"},
        "label": {"font": "spacemono-bold", "size": 50, "anim": "typewriter", "position": "lower"},
    },
}

# Reels UI covers roughly the top 220px and bottom 420px, and the right edge has buttons
SAFE: dict = {}
BANDS: dict = {}


def relayout() -> None:
    """The safe area and the rows text may sit in, for the frame being made (CANVAS)."""
    W, H = CANVAS.size
    BANDS.clear()
    if CANVAS.horizontal:
        # a horizontal reel plays as a band across the screen: the app's buttons sit outside it, so the words
        # only keep clear of the edges
        SAFE.update({"top": 70, "bottom": H - 80, "left": 130, "right": W - 130})
        BANDS.update({"upper": (90, 440), "center": (330, 750), "lower": (640, 990)})
    else:
        SAFE.update({"top": 250, "bottom": H - 440, "left": 80, "right": W - 150})
        BANDS.update({"upper": (300, 760), "center": (720, 1200), "lower": (1050, 1440)})


relayout()
CANVAS.listeners.append(relayout)


def scaled(cfg: dict) -> dict:
    """A text style's sizes for the frame being made (lettering is set bigger on a horizontal reel)."""
    k = CANVAS.text
    if k == 1.0:
        return cfg
    return {**cfg, **{key: int(round(float(cfg[key]) * k)) for key in ("size", "sub_size", "mono_size", "lead_size")
                      if isinstance(cfg.get(key), (int, float))}}

_font_cache: dict = {}


def font(name: str | None, size: int) -> ImageFont.FreeTypeFont:
    name = name or "montserrat"
    if name.lower() in FONTS:  # bundled names are case-insensitive; a path keeps its case
        name = name.lower()
    key = (name, size)
    if key in _font_cache:
        return _font_cache[key]
    if name in FONTS:
        file, weight = FONTS[name]
        f = ImageFont.truetype(str(FONT_DIR / file), size)
        if weight:
            try:
                f.set_variation_by_axes([weight])
            except Exception:
                pass
    elif name.startswith("gf:"):  # a font from the library (fontlib), fetched once
        from . import fontlib
        fam = fontlib.parse(name)
        p = fontlib.get(*fam) if fam else None
        f = ImageFont.truetype(str(p if p else FONT_DIR / FONTS["montserrat"][0]), size)
    else:  # a path to the user's own font
        try:
            f = ImageFont.truetype(str(Path(name).expanduser()), size)
        except OSError:
            f = ImageFont.truetype(str(FONT_DIR / FONTS["montserrat"][0]), size)
    _font_cache[key] = f
    return f


# ------------------------------------------------------------------ sprites
@dataclass
class Sprite:
    img: np.ndarray       # premultiplied-ready RGBA float32 0..1, padded for the shadow
    x: float              # final top-left of the padded sprite on the frame
    y: float
    t_in: float           # when its entrance starts (seconds from element start)
    group: int = 0        # line index (for masked reveals)
    clip: tuple | None = None  # (y0, y1) frame rows it may occupy while revealing
    anim: str | None = None    # per-sprite animation override
    behind: bool = False       # drawn behind the foreground (mountains etc.)
    knock: np.ndarray | None = None  # letter mask filled with the picture itself (see-through postcard letters)


LOOKS = ("neon", "glow", "outline", "offset")   # text looks (the effects library): how the letters are drawn


def _render_text(text: str, fnt, fill=(255, 255, 255), shadow: float = 0.55, stroke: int = 0,
                 tracking: float = 0.0, fills: list | None = None, look: str | None = None,
                 accent=(255, 210, 60)) -> tuple[np.ndarray, int]:
    """RGBA sprite of one piece of text with a soft drop shadow. Returns (array, pad).
    fills: a colour per character (postcard lettering) instead of one `fill`.
    look: neon (a coloured halo, letters near white), glow (a soft white halo), outline (hollow letters),
    offset (a hard copy behind in the accent colour)."""
    asc, desc = fnt.getmetrics()
    if tracking:
        widths = [fnt.getlength(c) for c in text]
        w = int(sum(widths) + tracking * max(0, len(text) - 1)) + 2
    else:
        w = int(math.ceil(fnt.getlength(text))) + 2
    h = asc + desc
    pad = max(12, int(h * (0.45 if look in ("neon", "glow") else 0.25)))
    if look == "outline" and not fills:
        shadow = 0.0   # a shadow would show through the hollow letters
    W, H = w + 2 * pad, h + 2 * pad
    txt = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(txt)

    def draw(dr, ox, oy, col, sw=0):
        if tracking:
            x = ox
            for c, cw in zip(text, widths):
                dr.text((x, oy), c, font=fnt, fill=col, stroke_width=sw, stroke_fill=col)
                x += cw + tracking
        else:
            dr.text((ox, oy), text, font=fnt, fill=col, stroke_width=sw, stroke_fill=col)

    if shadow > 0:
        sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        draw(ImageDraw.Draw(sh), pad + 2, pad + max(2, h // 22), (0, 0, 0, int(255 * shadow)), max(1, h // 30))
        txt = Image.alpha_composite(txt, sh.filter(ImageFilter.GaussianBlur(max(3, h / 14))))
        d = ImageDraw.Draw(txt)
    if stroke:
        draw(d, pad, pad, (0, 0, 0, 200), stroke)
    if look in ("neon", "glow"):
        halo = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        col = (*fill, 255) if look == "neon" else (255, 255, 255, 200)
        draw(ImageDraw.Draw(halo), pad, pad, col, max(2, h // 14))
        for r in (h / 5, h / 11):
            txt = Image.alpha_composite(txt, halo.filter(ImageFilter.GaussianBlur(r)))
        d = ImageDraw.Draw(txt)
        if look == "neon":   # the tube itself burns almost white
            fill = tuple(int(255 - (255 - c) * 0.25) for c in fill)
    elif look == "offset":
        k = max(3, h // 12)
        draw(d, pad + k, pad + k, (*[int(c) for c in accent[:3]], 255))
    elif look == "outline" and not fills:
        sw = max(2, h // 20)
        ring = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        draw(ImageDraw.Draw(ring), pad, pad, (*fill, 255), sw)
        hole = Image.new("L", (W, H), 0)
        hd = ImageDraw.Draw(hole)
        if tracking:
            x = pad
            for c, cw in zip(text, widths):
                hd.text((x, pad), c, font=fnt, fill=255)
                x += cw + tracking
        else:
            hd.text((pad, pad), text, font=fnt, fill=255)
        r = np.asarray(ring).copy()
        r[..., 3] = (r[..., 3].astype(np.float32) * (1 - np.asarray(hole, np.float32) / 255.0)).astype(np.uint8)
        txt = Image.alpha_composite(txt, Image.fromarray(r))
        return np.asarray(txt).astype(np.float32) / 255.0, pad
    if fills:
        x = float(pad)
        for i, c in enumerate(text):
            if not tracking:  # where the letter sits in the whole word (keeps the kerning)
                x = pad + fnt.getlength(text[:i])
            d.text((x, pad), c, font=fnt, fill=(*[int(v) for v in fills[i % len(fills)][:3]], 255))
            if tracking:
                x += widths[i] + tracking
    else:
        draw(d, pad, pad, (*fill, 255))
    return np.asarray(txt).astype(np.float32) / 255.0, pad


def _render_knock(text: str, fnt) -> tuple[np.ndarray, np.ndarray, int]:
    """Postcard block letters: a light rim, a dark extruded edge and a soft shadow as an RGBA sprite, and the
    letters' own shape as a mask that is filled with the picture behind them, boosted (see-through letters)."""
    asc, desc = fnt.getmetrics()
    h = asc + desc
    w = int(math.ceil(fnt.getlength(text))) + 2
    depth = max(3, h // 14)
    pad = max(14, int(h * 0.3)) + depth
    W, H = w + 2 * pad, h + 2 * pad
    sw = max(2, h // 26)
    base = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(sh).text((pad + depth + 3, pad + depth + 4), text, font=fnt, fill=(0, 0, 0, 150),
                            stroke_width=sw * 2, stroke_fill=(0, 0, 0, 150))
    base = Image.alpha_composite(base, sh.filter(ImageFilter.GaussianBlur(max(3, h / 16))))
    d = ImageDraw.Draw(base)
    for k in range(depth, 0, -1):  # the letters' thickness, going back down-right
        d.text((pad + k, pad + k), text, font=fnt, fill=(70, 18, 12, 255), stroke_width=sw, stroke_fill=(40, 10, 8, 255))
    d.text((pad, pad), text, font=fnt, fill=(255, 255, 255, 255), stroke_width=sw, stroke_fill=(255, 248, 225, 255))
    m = Image.new("L", (W, H), 0)
    ImageDraw.Draw(m).text((pad, pad), text, font=fnt, fill=255)
    return np.asarray(base).astype(np.float32) / 255.0, np.asarray(m).astype(np.float32) / 255.0, pad


def _knock_fill(frame: np.ndarray, mask: np.ndarray, x: int, y: int, alpha: float,
                src: np.ndarray | None = None) -> np.ndarray:
    """Fill the letter mask with the picture under it (`src`, the frame before any text), saturated and
    brightened like a postcard print."""
    src = frame if src is None else src
    H, W = frame.shape[:2]
    h, w = mask.shape
    fx0, fy0, fx1, fy1 = max(x, 0), max(y, 0), min(x + w, W), min(y + h, H)
    if fx1 <= fx0 or fy1 <= fy0:
        return frame
    m = mask[fy0 - y:fy1 - y, fx0 - x:fx1 - x, None] * alpha
    reg = frame[fy0:fy1, fx0:fx1].astype(np.float32)
    hsv = cv2.cvtColor(src[fy0:fy1, fx0:fx1], cv2.COLOR_RGB2HSV).astype(np.float32)
    hsv[..., 1] = np.clip(hsv[..., 1] * 1.7 + 25, 0, 255)
    hsv[..., 2] = np.clip(hsv[..., 2] * 1.15 + 20, 0, 255)
    vivid = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2RGB).astype(np.float32)
    shade = np.linspace(1.08, 0.86, fy1 - fy0, dtype=np.float32)[:, None, None]  # a little light from above
    vivid = np.clip(vivid * shade, 0, 255)
    if frame.flags.writeable is False:
        frame = frame.copy()
    frame[fy0:fy1, fx0:fx1] = (reg * (1 - m) + vivid * m).astype(np.uint8)
    return frame


def _wrap(words: list[str], fnt, max_w: float, space: float) -> list[list[str]]:
    lines = _wrap_greedy(words, fnt, max_w, space)
    if len(lines) < 2:
        return lines
    # balance the lines: the narrowest measure that still needs no more lines, so a title never leaves one word
    # hanging under a full line ("The urge to keep / driving." reads as "The urge to / keep driving.")
    def width(ls):
        return max(sum(fnt.getlength(w) for w in ln) + space * (len(ln) - 1) for ln in ls)
    lo, hi = max(fnt.getlength(w) for w in words), width(lines) + 1.0  # (+1: the sums round differently)
    for _ in range(12):
        mid = (lo + hi) / 2
        if len(_wrap_greedy(words, fnt, mid, space)) <= len(lines):
            hi = mid
        else:
            lo = mid
    return _wrap_greedy(words, fnt, hi, space)


def _wrap_greedy(words: list[str], fnt, max_w: float, space: float) -> list[list[str]]:
    lines, cur, cw = [], [], 0.0
    for w in words:
        ww = fnt.getlength(w)
        if cur and cw + space + ww > max_w:
            lines.append(cur)
            cur, cw = [w], ww
        else:
            cw = cw + (space if cur else 0) + ww
            cur.append(w)
    if cur:
        lines.append(cur)
    return lines


# --------------------------------------------------------------- elements
@dataclass
class TextElement:
    start: float
    duration: float
    anim: str
    sprites: list = field(default_factory=list)
    box: tuple = (0, 0, 0, 0)       # x0, y0, x1, y1 of the laid-out block (for scrim + placement)
    scrim: float = 0.0
    fill_lum: float = 1.0    # how light the letters are (0..1): light letters get shade when what's behind brightens
    exit: float = 0.28
    beats: list = field(default_factory=list)
    masker: object = None    # callable(frame) -> foreground mask, for sprites drawn behind
    lines: list = field(default_factory=list)  # [{text, x, y, font, size, tracking}] as laid out (hfx.py)
    kind: str = ""

    # ---------------------------------------------------------- animation
    def _sprite_state(self, s: Sprite, t: float):
        """(alpha, scale, dx, dy, reveal 0..1) for a sprite at element-local time t."""
        end_t = self.duration
        out_k = 1.0
        if t > end_t - self.exit:  # exit: fade + small drift
            q = min(1.0, (t - (end_t - self.exit)) / self.exit)
            out_k = 1 - q
        local = t - s.t_in
        if local < 0:
            return 0.0, 1.0, 0.0, 0.0, 0.0
        a = s.anim or self.anim
        if a == "rise":  # rises up from behind the skyline
            q = min(1.0, local / 1.1)
            e = 1 - (1 - q) ** 3
            return min(1.0, local / 0.25) * out_k, 1.0, 0, (1 - e) * 0.6, e
        if a == "pop":
            q = min(1.0, local / 0.2)
            back = 1 + 2.2 * (q - 1) ** 3 + 1.2 * (q - 1) ** 2 if q < 1 else 1.0  # ease-out-back
            sc = 1.45 - 0.45 * back
            return min(1.0, local / 0.06) * out_k, sc * (1 - 0.06 * (1 - out_k)), 0, 0, 1.0
        if a == "slide":
            q = min(1.0, local / 0.42)
            e = 1 - (1 - q) ** 3
            return out_k, 1.0, 0, (1 - e) * 1.0, e  # dy as fraction of sprite height (masked)
        if a == "typewriter":
            return (1.0 if local >= 0 else 0.0) * out_k, 1.0, 0, 0, 1.0
        if a == "tracking":
            q = min(1.0, local / 0.9)
            e = 1 - (1 - q) ** 3
            return min(1.0, local / 0.45) * out_k, 1.0, 0, 0, e
        if a == "scale":
            q = min(1.0, local / 0.35)
            e = 1 - (1 - q) ** 3
            return min(1.0, local / 0.2) * out_k, 0.82 + 0.18 * e, 0, 0, 1.0
        if a == "cut":  # there on the syllable, no fade: a word sung, then the next one in its place
            q = min(1.0, local / 0.1)
            return out_k, 1.05 - 0.05 * q, 0, 0, 1.0
        # fade
        q = min(1.0, local / 0.35)
        return q * out_k, 1.03 - 0.03 * q, 0, 0, 1.0

    def draw(self, frame: np.ndarray, t_abs: float) -> np.ndarray:
        t = t_abs - self.start
        if t < 0 or t > self.duration:
            return frame
        out = frame
        # what is behind the words now (a line held across shots, a pan onto a bright sky): light letters on a
        # light picture get a shade under them, measured on this frame
        shade = max(self.scrim, shade_needed(frame, self.box, self.fill_lum))
        if shade > 0:
            out = _scrim(out, self.box, shade * min(1.0, t / 0.3, (self.duration - t) / 0.3))
        cx_block = (self.box[0] + self.box[2]) / 2
        behind = [s for s in self.sprites if s.behind]
        if behind and self.masker is not None:
            clean = frame
            m = self.masker(clean)
            if m is not None:
                drawn = out.copy() if out is frame else out
                rows = [frame.shape[0], 0]
                for s in behind:
                    a, sc, dx, dy, rev = self._sprite_state(s, t)
                    if a <= 0.01:
                        continue
                    h = s.img.shape[0]
                    y = s.y + dy * h
                    drawn = _blend(drawn, s.img, int(round(s.x)), int(round(y)), a)
                    rows = [min(rows[0], int(y)), max(rows[1], int(y + h))]
                r0, r1 = max(0, rows[0]), min(frame.shape[0], rows[1])
                if r1 > r0:  # put the foreground back on top of the text
                    mm = m[r0:r1, :, None]
                    drawn[r0:r1] = (drawn[r0:r1] * (1 - mm) + clean[r0:r1] * mm).astype(np.uint8)
                out = drawn
        for s in self.sprites:
            if s.behind:
                continue
            a, sc, dx, dy, rev = self._sprite_state(s, t)
            if a <= 0.01:
                continue
            img = s.img
            x, y = s.x + dx, s.y
            if self.anim == "tracking" and rev < 1:
                # letters start bunched towards the block centre and spread to their places
                cx = s.x + img.shape[1] / 2
                x = s.x + (cx_block - cx) * 0.22 * (1 - rev)
            if abs(sc - 1) > 0.01:
                h, w = img.shape[:2]
                nw, nh = max(1, int(w * sc)), max(1, int(h * sc))
                img = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
                x -= (nw - w) / 2
                y -= (nh - h) / 2
            clip = None
            if (s.anim or self.anim) == "slide":
                h = img.shape[0]
                y = s.y + dy * h * 0.7
                clip = (s.y, s.y + h)  # masked: only visible inside its own line box
            out = _blend(out, img, int(round(x)), int(round(y)), a, clip)
            if s.knock is not None:
                km = s.knock if img is s.img else cv2.resize(s.knock, (img.shape[1], img.shape[0]))
                out = _knock_fill(out, km, int(round(x)), int(round(y)), a, frame)
        return out


def _scrim(frame: np.ndarray, box, strength: float) -> np.ndarray:
    """Soft dark gradient behind text so it reads on bright skies."""
    if strength <= 0.01:
        return frame
    x0, y0, x1, y1 = box
    pad = 220  # wide, soft falloff so it reads as shade, not a box
    y0, y1 = max(0, int(y0 - pad)), min(frame.shape[0], int(y1 + pad))
    if y1 <= y0:
        return frame
    h = y1 - y0
    ramp = np.sin(np.linspace(0, np.pi, h)) ** 1.2 * strength
    out = frame.copy()
    region = out[y0:y1].astype(np.float32)
    region *= (1 - ramp)[:, None, None]
    out[y0:y1] = region.astype(np.uint8)
    return out


def _blend(frame: np.ndarray, rgba: np.ndarray, x: int, y: int, alpha: float, clip=None) -> np.ndarray:
    H, W = frame.shape[:2]
    h, w = rgba.shape[:2]
    y_lo, y_hi = 0, H
    if clip:
        y_lo, y_hi = max(0, int(clip[0])), min(H, int(clip[1]))
    fx0, fy0 = max(x, 0), max(y, y_lo)
    fx1, fy1 = min(x + w, W), min(y + h, y_hi)
    if fx1 <= fx0 or fy1 <= fy0:
        return frame
    sx0, sy0 = fx0 - x, fy0 - y
    src = rgba[sy0:sy0 + (fy1 - fy0), sx0:sx0 + (fx1 - fx0)]
    a = src[..., 3:4] * alpha
    if frame.flags.writeable is False:
        frame = frame.copy()
    region = frame[fy0:fy1, fx0:fx1].astype(np.float32)
    region = region * (1 - a) + src[..., :3] * 255.0 * a
    frame[fy0:fy1, fx0:fx1] = region.astype(np.uint8)
    return frame


# ------------------------------------------------------------- placement
def busy_map_score(frame: np.ndarray, y0: int, y1: int) -> float:
    """How busy/bright a horizontal band is (lower = better place for text)."""
    band = frame[y0:y1, SAFE["left"]:SAFE["right"]]
    small = cv2.resize(band, (band.shape[1] // 4, max(1, band.shape[0] // 4)), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 60, 140).mean() / 255.0
    var = gray.std() / 128.0
    return edges * 3 + var


def choose_band(frame: np.ndarray | None, preferred: str, subject: dict | None = None) -> str:
    if preferred in BANDS:
        return preferred
    if frame is None:
        return "upper"
    scores = {}
    for name, (y0, y1) in BANDS.items():
        s = busy_map_score(frame, y0, y1)
        if subject:  # keep text off the subject
            sy0 = subject.get("y0", 0) * CANVAS.h
            sy1 = subject.get("y1", 0) * CANVAS.h
            overlap = max(0.0, min(y1, sy1) - max(y0, sy0)) / (y1 - y0)
            s += overlap * 1.5
        if name == "center":
            s += 0.15  # slight preference for the thirds over dead centre
        scores[name] = s
    return min(scores, key=scores.get)


def shade_needed(frame: np.ndarray | None, box, fill_lum: float) -> float:
    """How much shade light letters need on this frame: none on a dark picture, up to 0.55 on a bright one
    (pale sky, sunlit aspens, white rock). Dark letters bring their own contrast (0)."""
    if frame is None or fill_lum < 0.6:
        return 0.0
    x0, y0, x1, y1 = [int(v) for v in box]
    y0, y1 = max(0, y0), min(frame.shape[0], max(y0 + 1, y1))
    x0, x1 = max(0, x0), min(frame.shape[1], max(x0 + 1, x1))
    patch = frame[y0:y1:4, x0:x1:4]
    if patch.size == 0:
        return 0.0
    lum = patch.reshape(-1, 3).astype(np.float32) @ np.float32([0.299, 0.587, 0.114]) / 255.0
    bg = 0.5 * float(lum.mean()) + 0.5 * float(np.percentile(lum, 75))   # the bright parts count most
    gap = fill_lum - bg                                                  # how much lighter the letters are
    return float(np.clip((0.55 - gap) * 1.1, 0.0, 0.55))


def face_rows(frame: np.ndarray | None) -> list[tuple[float, float]]:
    """(top, bottom) in pixels of the faces in a frame (a little head room above, chin below), when the face
    model is there."""
    if frame is None:
        return []
    import cv2
    from .nodes import _faces
    h, w = frame.shape[:2]
    k = 480 / max(h, w)
    small = cv2.cvtColor(cv2.resize(frame, (int(w * k), int(h * k))), cv2.COLOR_RGB2BGR)
    return [((fy - 0.35 * fh) * h, (fy + 1.15 * fh) * h) for fx, fy, fw, fh in _faces(small) if fw * fh > 0.0015]


def band_brightness(frame: np.ndarray | None, box) -> float:
    if frame is None:
        return 0.5
    x0, y0, x1, y1 = [int(v) for v in box]
    y0, y1 = max(0, y0), min(frame.shape[0], max(y0 + 1, y1))
    x0, x1 = max(0, x0), min(frame.shape[1], max(x0 + 1, x1))
    return float(frame[y0:y1, x0:x1].mean() / 255.0)


def colour_clash(frame: np.ndarray | None, box, fill) -> bool:
    """Coloured letters about the colour of what is behind them. White and near-white type is left to the
    brightness checks; a red, yellow or blue line is compared with the picture's own colour under it."""
    if frame is None or min(fill[:3]) > 200:
        return False
    x0, y0, x1, y1 = [int(v) for v in box]
    y0, y1 = max(0, y0), min(frame.shape[0], max(y0 + 1, y1))
    x0, x1 = max(0, x0), min(frame.shape[1], max(x0 + 1, x1))
    patch = frame[y0:y1, x0:x1].reshape(-1, 3).astype(np.float32)
    if not len(patch):
        return False
    near = np.linalg.norm(patch - np.asarray(fill[:3], np.float32), axis=1) < 90
    return float(near.mean()) > 0.2   # a fifth of the ground behind the words is about their colour


# --------------------------------------------------------------- builders
def _beat_steps(start: float, n: int, beats: list[float], duration: float) -> list[float]:
    """Entrance times for n items: on the beat when beats are close enough, else 0.12s apart."""
    if n <= 1:
        return [0.0]
    budget = max(0.3, duration * 0.45)
    cand = [b - start for b in beats if 0 <= b - start <= budget]
    if len(cand) >= n:
        if cand[0] > 0.15:
            cand = [0.0] + cand
        return cand[:n]
    halves = []  # try half-beats
    for a, b in zip(beats, beats[1:]):
        for v in (a, (a + b) / 2):
            if 0 <= v - start <= budget:
                halves.append(v - start)
    if len(halves) >= n:
        return halves[:n]
    step = min(0.12, budget / n)
    return [i * step for i in range(n)]


def script_cfg(text: str, cfg: dict) -> dict:
    """Text in another script (Malayalam, Hindi, Arabic, Japanese...): a font that has its letters, no
    letter-by-letter animation (it would break up joined letters), whole lines for right-to-left text."""
    from .scripts import font_for, script_of
    sc = script_of(text)
    if not sc:
        return cfg
    from . import fontlib
    fam = fontlib.parse(cfg.get("font"))
    if fam and sc in fontlib.CATALOG.get(fam[0], ("", (), ()))[2]:  # the chosen face has these letters
        out = {**cfg, "uppercase": False, "script": sc}
        if out.get("anim") in ("typewriter", "tracking"):
            out["anim"] = "slide"
        return out
    path = font_for(sc)
    if path is None:
        return cfg
    out = {**cfg, "font": str(path), "uppercase": False, "size": int(int(cfg.get("size", 100)) * 0.9),
           "script": sc}
    if out.get("anim") in ("typewriter", "tracking") or sc in ("arabic", "hebrew"):
        out["anim"] = "slide"
    return out


def clear_rows(top: float, h: float, avoid, gap: float = 18.0) -> float:
    """Where a text block of height h, wanted at `top`, sits clear of the subject: avoid = (subject top, subject
    bottom, picture top, picture bottom) in pixels. The nearer free side that still fits in the picture; else
    it stays where it was."""
    if not avoid:
        return top
    s0, s1, lo, hi = avoid
    if top + h <= s0 - gap or top >= s1 + gap:
        return top
    sides = [t for t in (s0 - gap - h, s1 + gap) if lo + gap <= t and t + h <= hi - gap]
    return min(sides, key=lambda t: abs(t - top)) if sides else top


def build_hook(text: str, start: float, duration: float, cfg: dict, frame: np.ndarray | None,
               beats: list[float], subject: dict | None = None, avoid=None, lead: str | None = None) -> TextElement:
    """A line (or up to three) of big lettering. cfg extras for a recipe's own words: `fit` (0..1: a short
    line is set as wide as that share of the safe width, like a postcard's place name), `colors` (a colour
    per letter), `fixed` (the block starts at the same height whatever it says, so a name that changes with
    every shot doesn't jump), `y` (the middle of the block, 0..1 down the frame, instead of the middle of its
    band), and with `lead` a small line above it (`lead_font`, `lead_size`)."""
    cfg = script_cfg(text, cfg)
    if cfg.get("uppercase"):
        text = text.upper()
    size = base_size = int(cfg.get("size", 100))
    fnt = font(cfg.get("font"), size)
    anim = cfg.get("anim", "pop")
    max_w = SAFE["right"] - SAFE["left"] - 40
    if cfg.get("fit") and text.strip():
        wide = fnt.getlength(text)
        k = min(2.2, float(cfg["fit"]) * max_w / max(1.0, wide))
        if k > 1.0 or wide > max_w and len(text.split()) <= 2:  # a short name grows; one or two words shrink to a line
            size = max(48, int(size * max(0.55, k)))
            fnt = font(cfg.get("font"), size)
    room = 0.45 * (SAFE["bottom"] - SAFE["top"])  # a title takes at most about half of the free screen
    while True:
        space = fnt.getlength(" ")
        lines = _wrap(text.split(), fnt, max_w, space)
        tall = len(lines) * sum(fnt.getmetrics()) * float(cfg.get("line_gap", 1.05))
        if (len(lines) <= 3 and tall <= room) or size < 48:
            break
        size = int(size * 0.88)
        fnt = font(cfg.get("font"), size)
    asc, desc = fnt.getmetrics()
    lh = int((asc + desc) * float(cfg.get("line_gap", 1.05)))
    band = choose_band(frame, cfg.get("position", "auto"), subject)
    by0, by1 = BANDS[band]
    lead_fnt = lead_h = None
    if lead:
        lead_size = int(cfg.get("lead_size") or max(40, base_size * 0.42))
        lead_fnt = font(cfg.get("lead_font") or "caveat", lead_size)
        while lead_fnt.getlength(lead) > max_w and lead_size > 30:
            lead_size = int(lead_size * 0.9)
            lead_fnt = font(cfg.get("lead_font") or "caveat", lead_size)
        lead_h = int(sum(lead_fnt.getmetrics()) * 0.95)
    block_h = lh * len(lines) + (lead_h or 0)
    if cfg.get("fixed"):  # placed as if it were one line of the plain size: what it says doesn't move it
        one = int(sum(font(cfg.get("font"), base_size).getmetrics()) * float(cfg.get("line_gap", 1.05)))
        top = by0 + max(0, (by1 - by0 - one - (lead_h or 0)) // 2)
        top = max(SAFE["top"], min(top, SAFE["bottom"] - block_h))
    else:
        top = by0 + max(0, (by1 - by0 - block_h) // 2)
        top = max(SAFE["top"], min(top, SAFE["bottom"] - block_h))  # (a tall block in a short band stays on screen)
    if cfg.get("y") is not None:  # the plan chose the height (a line held across shots: recipes.free_row)
        top = max(SAFE["top"], min(int(float(cfg["y"]) * CANVAS.h - block_h / 2), SAFE["bottom"] - block_h))
        avoid = None
    ink0, ink1 = (asc * 0.22, asc * 1.02) if text.upper() == text else (asc * 0.2, asc + desc * 0.8)
    if avoid and not cfg.get("fixed"):
        # the letters, not the line box, must clear the subject (capitals leave the descender row empty)
        top = int(round(clear_rows(top + ink0, block_h - lh + ink1 - ink0, avoid) - ink0))
    for f0, f1 in face_rows(frame):  # never across a face, wherever the line was meant to sit
        top = int(round(clear_rows(top + ink0, block_h - lh + ink1 - ink0,
                                   (f0, f1, SAFE["top"] - 18, SAFE["bottom"] + 18)) - ink0))
    el = TextElement(start, duration, anim, beats=beats)
    if cfg.get("exit") is not None:
        el.exit = max(0.01, float(cfg["exit"]))
    fill = tuple(int(c) for c in cfg["color"][:3]) if cfg.get("color") else (255, 255, 255)
    el.fill_lum = 0.0 if cfg.get("fill") == "picture" else (0.299 * fill[0] + 0.587 * fill[1] + 0.114 * fill[2]) / 255.0
    palette = cfg.get("colors") if isinstance(cfg.get("colors"), list) and cfg.get("colors") else None
    inked = 0  # letters drawn so far: the colours run on through the lines
    items = []  # (text, x, y, line)
    widths = []
    line_w = [sum(fnt.getlength(w) for w in ws) + space * (len(ws) - 1) for ws in lines]
    dx = 0.0
    if cfg.get("x") is not None:  # the block's middle across the frame, as the reference has it (0..1)
        half = max(line_w + [lead_fnt.getlength(lead) if lead else 0]) / 2
        mid = min(max(float(cfg["x"]) * CANVAS.w, SAFE["left"] + 20 + half), SAFE["right"] - 20 - half)
        dx = mid - (SAFE["left"] + 20 + max_w / 2)
    if lead:
        lw = lead_fnt.getlength(lead)
        widths.append(lw)
        lx = SAFE["left"] + 20 + (max_w - lw) / 2 + dx
        if cfg.get("fill") == "picture" and line_w:  # a postcard's script line starts over the name's left edge
            lx = SAFE["left"] + 20 + (max_w - line_w[0]) / 2 + dx - 0.04 * line_w[0]
        el.lines.append({"text": lead, "x": lx, "y": top, "font": cfg.get("lead_font") or "caveat",
                         "size": lead_fnt.size, "tracking": 0.0, "h": lead_h, "role": "lead"})
        lead_fill = tuple(int(c) for c in cfg["lead_color"][:3]) if cfg.get("lead_color") else (255, 255, 255)
        img, pad = _render_text(lead, lead_fnt, fill=lead_fill, shadow=0.7, stroke=max(1, lead_size // 24)
                                if cfg.get("lead_color") else 0)
        el.sprites.append(Sprite(img, lx - pad, top - pad, 0.0, 0))
        top += lead_h
    for li, words in enumerate(lines):
        lw = line_w[li]
        widths.append(lw)
        x = SAFE["left"] + 20 + (max_w - lw) / 2 + dx
        y = top + li * lh
        el.lines.append({"text": " ".join(words), "x": x, "y": y, "font": cfg.get("font"), "size": size,
                         "tracking": 0.0, "h": lh})
        if anim in ("pop", "scale"):
            for w in words:
                items.append((w, x, y, li))
                x += fnt.getlength(w) + space
        elif anim in ("typewriter", "tracking"):
            line = " ".join(words)
            for c in line:
                items.append((c, x, y, li))
                x += fnt.getlength(c)
        else:
            items.append((" ".join(words), x, y, li))
    x0 = SAFE["left"] + 20 + (max_w - max(widths)) / 2 + dx
    top -= lead_h or 0
    el.box = (x0, top, x0 + max(widths), top + block_h)
    bright = band_brightness(frame, el.box)
    el.scrim = 0.34 if bright > 0.62 else (0.2 if bright > 0.45 else 0.0)
    if frame is not None and cfg.get("legible", True):
        # busy texture behind the words (rock, foliage, waves) eats thin type: shade it
        busy = busy_map_score(frame, max(0, int(el.box[1])), min(frame.shape[0], int(el.box[3]) + 1))
        if busy > 0.55:
            el.scrim = max(el.scrim, 0.3)
    edge = 0
    if frame is not None and not palette and colour_clash(frame, el.box, fill):
        # red letters on a red rock (an example's colour over our picture): outline them and shade behind
        edge, el.scrim = max(2, size // 26), max(el.scrim, 0.3)
    # entrance times
    if cfg.get("fast_in") and anim in ("pop", "scale", "typewriter"):
        # the opening line must read within the first second: every word in by about 0.5 s
        times = [min(0.5, 0.07 * i) for i in range(len(items))] if anim != "typewriter" else \
            [min(0.6, 0.6 * i / max(1, len(items))) for i in range(len(items))]
    elif anim == "pop":
        times = _beat_steps(start, len(items), beats, duration)
    elif anim == "typewriter":
        cps = max(14.0, len(items) / max(0.6, duration * 0.4))
        times = [i / cps for i in range(len(items))]
    elif anim == "slide":
        times = [0.09 * it[3] for it in items]
    elif anim == "tracking":
        times = [0.0 for _ in items]
    elif anim == "cut":
        times = [0.0 for _ in items]
    else:
        times = [0.07 * i for i in range(len(items))]
    for (txt, x, y, li), ti in zip(items, times):
        if txt == " ":
            continue
        fills = None
        if palette:
            fills, n = [], inked
            for c in txt:
                fills.append(palette[n % len(palette)])
                n += 0 if c == " " else 1
            inked = n
        if cfg.get("fill") == "picture":  # see-through letters: the picture shows inside them
            img, km, pad = _render_knock(txt, fnt)
            el.sprites.append(Sprite(img, x - pad, y - pad, ti, li, knock=km))
            continue
        look = cfg.get("look") if cfg.get("look") in LOOKS else None
        img, pad = _render_text(txt, fnt, fill=fill, shadow=0 if look == "neon" else (0.6 if el.scrim < 0.3 else 0.45),
                                fills=fills, stroke=max(2, size // 36) if palette else edge, look=look,
                                accent=tuple(cfg.get("lead_color") or (255, 210, 60)))
        el.sprites.append(Sprite(img, x - pad, y - pad, ti, li))
    return el


CAPTION = {"font": "montserrat-bold", "size": 58, "anim": "slide", "uppercase": False, "line_gap": 1.1,
           "position": "lower", "legible": True}
# smallest sizes (px at 1080 wide) that still read on a phone held at arm's length
MIN_SIZE = {"hook": 88, "label": 64, "cta": 60, "caption": 54}


def legible(kind: str, cfg: dict) -> dict:
    """Bump a text style up to readable sizes (a minimal preset can stay elegant, not tiny)."""
    cfg = dict(cfg)
    if kind in MIN_SIZE:
        cfg["size"] = max(int(cfg.get("size", MIN_SIZE[kind])), MIN_SIZE[kind])
    if kind == "location":
        if cfg.get("layout") == "line":
            cfg["size"] = max(int(cfg.get("size", 40)), 54)
        cfg["sub_size"] = max(int(cfg.get("sub_size", 30)), 34)
        cfg["mono_size"] = max(int(cfg.get("mono_size", 24)), 28)
    return cfg


def build_location(main: str, sub: str | None, coords: str | None, start: float, duration: float,
                   cfg: dict, frame: np.ndarray | None, subject: dict | None = None) -> TextElement:
    from .scripts import font_for, script_of
    for key, txt in (("font", main), ("sub_font", sub)):
        sc = script_of(txt or "")
        if sc and font_for(sc):  # a place name in its own script (മൂന്നാർ, 東京)
            cfg = {**cfg, key: str(font_for(sc))}
            if cfg.get("anim") in ("typewriter", "tracking") or sc in ("arabic", "hebrew"):
                cfg["anim"] = "slide"
    layout = cfg.get("layout", "title")
    anim = cfg.get("anim", "slide")
    el = TextElement(start, duration, anim)
    lines = []  # (text, font, tracking)
    if layout == "title":
        big = font(cfg.get("font", "bebas"), int(cfg.get("size", 140)))
        main_u = main.upper() if cfg.get("font", "bebas") in ("bebas", "anton", "archivo") else main
        # shrink the big line to fit the safe width
        size = int(cfg.get("size", 140))
        while big.getlength(main_u) > SAFE["right"] - SAFE["left"] - 20 and size > 50:
            size = int(size * 0.9)
            big = font(cfg.get("font", "bebas"), size)
        lines.append((main_u, big, 0.0))
        names = [(cfg.get("font", "bebas"), size)]
        if sub:
            # the spaced-out line under it fits the safe width too ("GLEN CANYON NATIONAL RECREATION AREA"):
            # smaller, then dropped rather than run off the screen
            ss = int(cfg.get("sub_size", 30))
            room = SAFE["right"] - SAFE["left"] - 20
            sf = font(cfg.get("sub_font", "montserrat"), ss)
            while sf.getlength(sub.upper()) + ss * 0.35 * (len(sub) - 1) > room and ss > 20:
                ss = int(ss * 0.9)
                sf = font(cfg.get("sub_font", "montserrat"), ss)
            if sf.getlength(sub.upper()) + ss * 0.35 * (len(sub) - 1) <= room:
                lines.append((sub.upper(), sf, ss * 0.35))
                names.append((cfg.get("sub_font", "montserrat"), ss))
        if coords:
            mf = font(cfg.get("mono_font", "spacemono"), int(cfg.get("mono_size", 24)))
            lines.append((coords, mf, 2.0))
            names.append((cfg.get("mono_font", "spacemono"), int(cfg.get("mono_size", 24))))
    else:  # one compact line: "MAIN · SUB" + coords under it
        lf = font(cfg.get("font", "montserrat"), int(cfg.get("size", 34)))
        label = main.upper() + (f"  ·  {sub.upper()}" if sub else "")
        lines.append((label, lf, int(cfg.get("size", 34)) * 0.18))
        names = [(cfg.get("font", "montserrat"), int(cfg.get("size", 34)))]
        if coords:
            mf = font(cfg.get("mono_font", "spacemono"), int(cfg.get("mono_size", 22)))
            lines.append((coords, mf, 1.5))
            names.append((cfg.get("mono_font", "spacemono"), int(cfg.get("mono_size", 22))))
    pos = cfg.get("position", "auto")
    if pos in ("lower_left", "upper_left"):
        pos = "lower" if pos == "lower_left" else "upper"
    band = choose_band(frame, pos if pos in BANDS else "auto", subject)
    heights = []
    for txt, f, tr in lines:
        a, d = f.getmetrics()
        heights.append(int((a + d) * (0.92 if f is lines[0][1] else 1.15)))
    block_h = sum(heights) + 10 * (len(lines) - 1)
    by0, by1 = BANDS[band]
    top = by0 + max(0, (by1 - by0 - block_h) // 2)
    left_align = layout != "title" or cfg.get("align", "left") == "left"
    y = top
    widths = []
    for li, ((txt, f, tr), lh) in enumerate(zip(lines, heights)):
        w = (sum(f.getlength(c) for c in txt) + tr * (len(txt) - 1)) if tr else f.getlength(txt)
        widths.append(w)
        x = SAFE["left"] + 10 if left_align else (CANVAS.w - w) / 2
        el.lines.append({"text": txt, "x": x, "y": y, "font": names[li][0], "size": names[li][1],
                         "tracking": float(tr), "h": lh, "role": ("main", "sub", "mono")[min(li, 2)]
                         if layout == "title" else ("main" if li == 0 else "mono")})
        if anim in ("typewriter", "tracking"):
            cx = x
            for ci, c in enumerate(txt):
                cw = f.getlength(c)
                if c != " ":
                    img, pad = _render_text(c, f, shadow=0.6)
                    el.sprites.append(Sprite(img, cx - pad, y - pad,
                                             (ci / 18.0 if anim == "typewriter" else 0.0) + 0.25 * li, li))
                cx += cw + tr
        else:
            img, pad = _render_text(txt, f, shadow=0.6, tracking=tr)
            el.sprites.append(Sprite(img, x - pad, y - pad, 0.12 * li, li))
        y += lh + 10
    x0 = SAFE["left"] if left_align else (CANVAS.w - max(widths)) / 2
    el.box = (x0, top, x0 + max(widths), top + block_h)
    bright = band_brightness(frame, el.box)
    el.scrim = 0.4 if bright > 0.6 else (0.2 if bright > 0.45 else 0.0)
    return el


def build_location_behind(main: str, sub: str | None, coords: str | None, start: float, duration: float,
                          cfg: dict, frame: np.ndarray | None) -> TextElement | None:
    """Giant place name tucked behind the skyline: peaks and buildings overlap the letters.

    Returns None when the frame has no clear sky/skyline, so the caller can fall back."""
    from .mask import MaskTracker, sky_mask, skyline
    if frame is None:
        return None
    m = sky_mask(frame)
    if m is None:
        return None
    text = main.upper()
    fname = cfg.get("behind_font", "anton")
    target_w = (SAFE["right"] + 70 - SAFE["left"]) * 0.97  # use (almost) the full width
    size = 520
    while size > 140:
        f = font(fname, size)
        if f.getlength(text) <= target_w:
            break
        size = int(size * 0.94)
    if size <= 140:
        return None
    f = font(fname, size)
    l, t_ink, r, b_ink = f.getbbox(text)
    ink_h = b_ink - t_ink
    tw = f.getlength(text)
    x = (CANVAS.w - tw) / 2
    sky_line = skyline(m)
    span = sky_line[int(max(0, x)):int(min(CANVAS.w, x + tw))]
    if span.size == 0:
        return None
    line_y = float(np.median(span))
    # bottom ~40% of the letters goes behind the land; the rest stands in the sky
    ink_top = line_y - 0.6 * ink_h
    if ink_top < SAFE["top"]:
        return None
    # check the letters really overlap the foreground (otherwise it's just normal text)
    y0, y1 = int(ink_top), int(min(CANVAS.h, ink_top + ink_h))
    cover = float(m[y0:y1, int(max(0, x)):int(min(CANVAS.w, x + tw))].mean()) if y1 > y0 else 0
    if not 0.12 <= cover <= 0.7:
        return None
    el = TextElement(start, duration, cfg.get("behind_anim", "rise"))
    el.masker = MaskTracker()
    img, pad = _render_text(text, f, shadow=0.35)
    el.sprites.append(Sprite(img, x - pad, ink_top - t_ink - pad, 0.0, 0, anim="rise", behind=True))
    # small lines in front, above the giant word
    extras = []
    if sub:
        sf = font(cfg.get("sub_font", "montserrat"), int(cfg.get("sub_size", 38)))
        extras.append((sub.upper(), sf, int(cfg.get("sub_size", 38)) * 0.35))
    if coords:
        mf = font(cfg.get("mono_font", "spacemono"), int(cfg.get("mono_size", 28)))
        extras.append((coords, mf, 2.0))
    y = ink_top - 24
    for i, (txt, ff, tr) in enumerate(reversed(extras)):
        a_, d_ = ff.getmetrics()
        y -= (a_ + d_)
        if y < SAFE["top"] - 20:
            break
        w = sum(ff.getlength(c) for c in txt) + tr * (len(txt) - 1)
        img, pad = _render_text(txt, ff, shadow=0.6, tracking=tr)
        el.sprites.append(Sprite(img, (CANVAS.w - w) / 2 - pad, y - pad, 0.45 + 0.12 * (len(extras) - 1 - i), 1,
                                 anim="slide"))
        y -= 8
    el.box = (x, y, x + tw, ink_top + ink_h)
    el.scrim = 0.0
    return el


def format_coords(gps) -> str | None:
    if not gps:
        return None
    lat, lon = gps
    return f"{abs(lat):.2f}° {'N' if lat >= 0 else 'S'}   {abs(lon):.2f}° {'E' if lon >= 0 else 'W'}"


def split_place(name: str) -> tuple[str, str | None]:
    parts = [p.strip() for p in name.split(",") if p.strip()]
    if not parts:
        return name, None
    return parts[0], (", ".join(parts[1:]) or None)
