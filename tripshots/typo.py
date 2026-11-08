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

from .config import OUT_H, OUT_W

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
SAFE = {"top": 250, "bottom": OUT_H - 440, "left": 80, "right": OUT_W - 150}
BANDS = {"upper": (300, 760), "center": (720, 1200), "lower": (1050, 1440)}

_font_cache: dict = {}


def font(name: str | None, size: int) -> ImageFont.FreeTypeFont:
    name = (name or "montserrat").lower()
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


def _render_text(text: str, fnt, fill=(255, 255, 255), shadow: float = 0.55, stroke: int = 0,
                 tracking: float = 0.0) -> tuple[np.ndarray, int]:
    """RGBA sprite of one piece of text with a soft drop shadow. Returns (array, pad)."""
    asc, desc = fnt.getmetrics()
    if tracking:
        widths = [fnt.getlength(c) for c in text]
        w = int(sum(widths) + tracking * max(0, len(text) - 1)) + 2
    else:
        w = int(math.ceil(fnt.getlength(text))) + 2
    h = asc + desc
    pad = max(12, int(h * 0.25))
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
    draw(d, pad, pad, (*fill, 255))
    return np.asarray(txt).astype(np.float32) / 255.0, pad


def _wrap(words: list[str], fnt, max_w: float, space: float) -> list[list[str]]:
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
    exit: float = 0.28
    beats: list = field(default_factory=list)
    masker: object = None    # callable(frame) -> foreground mask, for sprites drawn behind

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
        # fade
        q = min(1.0, local / 0.35)
        return q * out_k, 1.03 - 0.03 * q, 0, 0, 1.0

    def draw(self, frame: np.ndarray, t_abs: float) -> np.ndarray:
        t = t_abs - self.start
        if t < 0 or t > self.duration:
            return frame
        out = frame
        if self.scrim > 0:
            out = _scrim(out, self.box, self.scrim * min(1.0, t / 0.3, (self.duration - t) / 0.3))
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
            sy0 = subject.get("y0", 0) * OUT_H
            sy1 = subject.get("y1", 0) * OUT_H
            overlap = max(0.0, min(y1, sy1) - max(y0, sy0)) / (y1 - y0)
            s += overlap * 1.5
        if name == "center":
            s += 0.15  # slight preference for the thirds over dead centre
        scores[name] = s
    return min(scores, key=scores.get)


def band_brightness(frame: np.ndarray | None, box) -> float:
    if frame is None:
        return 0.5
    x0, y0, x1, y1 = [int(v) for v in box]
    y0, y1 = max(0, y0), min(frame.shape[0], max(y0 + 1, y1))
    x0, x1 = max(0, x0), min(frame.shape[1], max(x0 + 1, x1))
    return float(frame[y0:y1, x0:x1].mean() / 255.0)


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


def build_hook(text: str, start: float, duration: float, cfg: dict, frame: np.ndarray | None,
               beats: list[float], subject: dict | None = None) -> TextElement:
    if cfg.get("uppercase"):
        text = text.upper()
    size = int(cfg.get("size", 100))
    fnt = font(cfg.get("font"), size)
    anim = cfg.get("anim", "pop")
    max_w = SAFE["right"] - SAFE["left"] - 40
    while True:
        space = fnt.getlength(" ")
        lines = _wrap(text.split(), fnt, max_w, space)
        if len(lines) <= 3 or size < 48:
            break
        size = int(size * 0.88)
        fnt = font(cfg.get("font"), size)
    asc, desc = fnt.getmetrics()
    lh = int((asc + desc) * float(cfg.get("line_gap", 1.05)))
    band = choose_band(frame, cfg.get("position", "auto"), subject)
    by0, by1 = BANDS[band]
    block_h = lh * len(lines)
    top = by0 + max(0, (by1 - by0 - block_h) // 2)
    el = TextElement(start, duration, anim, beats=beats)
    items = []  # (text, x, y, line)
    widths = []
    for li, words in enumerate(lines):
        lw = sum(fnt.getlength(w) for w in words) + space * (len(words) - 1)
        widths.append(lw)
        x = SAFE["left"] + 20 + (max_w - lw) / 2
        y = top + li * lh
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
    x0 = SAFE["left"] + 20 + (max_w - max(widths)) / 2
    el.box = (x0, top, x0 + max(widths), top + block_h)
    bright = band_brightness(frame, el.box)
    el.scrim = 0.34 if bright > 0.62 else (0.2 if bright > 0.45 else 0.0)
    if frame is not None and cfg.get("legible", True):
        # busy texture behind the words (rock, foliage, waves) eats thin type: shade it
        busy = busy_map_score(frame, max(0, int(el.box[1])), min(frame.shape[0], int(el.box[3]) + 1))
        if busy > 0.55:
            el.scrim = max(el.scrim, 0.3)
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
    else:
        times = [0.07 * i for i in range(len(items))]
    for (txt, x, y, li), ti in zip(items, times):
        if txt == " ":
            continue
        img, pad = _render_text(txt, fnt, shadow=0.6 if el.scrim < 0.3 else 0.45)
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
        if sub:
            sf = font(cfg.get("sub_font", "montserrat"), int(cfg.get("sub_size", 30)))
            lines.append((sub.upper(), sf, int(cfg.get("sub_size", 30)) * 0.35))
        if coords:
            mf = font(cfg.get("mono_font", "spacemono"), int(cfg.get("mono_size", 24)))
            lines.append((coords, mf, 2.0))
    else:  # one compact line: "MAIN · SUB" + coords under it
        lf = font(cfg.get("font", "montserrat"), int(cfg.get("size", 34)))
        label = main.upper() + (f"  ·  {sub.upper()}" if sub else "")
        lines.append((label, lf, int(cfg.get("size", 34)) * 0.18))
        if coords:
            mf = font(cfg.get("mono_font", "spacemono"), int(cfg.get("mono_size", 22)))
            lines.append((coords, mf, 1.5))
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
        x = SAFE["left"] + 10 if left_align else (OUT_W - w) / 2
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
    x0 = SAFE["left"] if left_align else (OUT_W - max(widths)) / 2
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
    x = (OUT_W - tw) / 2
    sky_line = skyline(m)
    span = sky_line[int(max(0, x)):int(min(OUT_W, x + tw))]
    if span.size == 0:
        return None
    line_y = float(np.median(span))
    # bottom ~40% of the letters goes behind the land; the rest stands in the sky
    ink_top = line_y - 0.6 * ink_h
    if ink_top < SAFE["top"]:
        return None
    # check the letters really overlap the foreground (otherwise it's just normal text)
    y0, y1 = int(ink_top), int(min(OUT_H, ink_top + ink_h))
    cover = float(m[y0:y1, int(max(0, x)):int(min(OUT_W, x + tw))].mean()) if y1 > y0 else 0
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
        el.sprites.append(Sprite(img, (OUT_W - w) / 2 - pad, y - pad, 0.45 + 0.12 * (len(extras) - 1 - i), 1,
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
