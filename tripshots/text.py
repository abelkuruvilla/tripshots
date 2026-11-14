"""Fonts, text overlay PNGs, contact sheets and storyboards (all Pillow)."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .config import CANVAS

FONT_CANDIDATES = {
    "bold": [
        "/System/Library/Fonts/Avenir Next.ttc",
        "/System/Library/Fonts/Supplemental/Futura.ttc",
        "/System/Library/Fonts/HelveticaNeue.ttc",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
    ],
    "regular": [
        "/System/Library/Fonts/Avenir Next.ttc",
        "/System/Library/Fonts/HelveticaNeue.ttc",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ],
}
# index inside .ttc collections that gives a bold/demibold face
_TTC_BOLD_INDEX = {"Avenir Next.ttc": 2, "Futura.ttc": 2, "HelveticaNeue.ttc": 1, "Helvetica.ttc": 1}


def load_font(size: int, weight: str = "bold", custom: str | None = None) -> ImageFont.ImageFont:
    cands = []
    if custom:
        p = Path(custom).expanduser()
        cands.append(str(p) if p.exists() else custom)
    cands += FONT_CANDIDATES[weight]
    for c in cands:
        try:
            idx = _TTC_BOLD_INDEX.get(Path(c).name, 0) if weight == "bold" else 0
            return ImageFont.truetype(c, size, index=idx)
        except (OSError, ValueError):
            continue
    return ImageFont.load_default(size=size)


def _wrap(draw, text, font, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def render_hook_png(text: str, out: Path, cfg: dict, font_name: str | None) -> Path:
    """Big title in the upper-safe area with a soft shadow (Reels UI covers top ~220px and bottom ~420px)."""
    if cfg.get("uppercase"):
        text = text.upper()
    size = int(cfg.get("size", 82))
    img = Image.new("RGBA", (CANVAS.w, CANVAS.h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    font = load_font(size, "bold", font_name)
    lines = _wrap(d, text, font, CANVAS.w - 220)
    lh = int(size * 1.18)
    y0 = {"upper": 330, "center": CANVAS.h // 2 - lh * len(lines) // 2, "lower": 1250}.get(cfg.get("position", "upper"), 330)
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    for i, line in enumerate(lines):
        w = d.textlength(line, font=font)
        x, y = (CANVAS.w - w) / 2, y0 + i * lh
        sd.text((x + 3, y + 4), line, font=font, fill=(0, 0, 0, 170))
        d.text((x, y), line, font=font, fill=(255, 255, 255, 255))
    shadow = shadow.filter(ImageFilter.GaussianBlur(8))
    Image.alpha_composite(shadow, img).save(out)
    return out


def render_location_png(text: str, out: Path, cfg: dict, font_name: str | None) -> Path:
    size = int(cfg.get("size", 40))
    img = Image.new("RGBA", (CANVAS.w, CANVAS.h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    font = load_font(size, "bold", font_name)
    tw = d.textlength(text, font=font)
    pin = int(size * 0.9)
    pos = cfg.get("position", "lower_left")
    y = {"lower_left": 1380, "upper_left": 260, "center": CANVAS.h // 2}.get(pos, 1380)
    x = 80 if "left" in pos else int((CANVAS.w - tw - pin - 16) / 2)
    # pill background
    pad = int(size * 0.45)
    d.rounded_rectangle([x - pad, y - pad, x + pin + 16 + tw + pad, y + size + pad],
                        radius=size, fill=(0, 0, 0, 95))
    # map-pin glyph
    cx, cy, r = x + pin / 2, y + pin * 0.38, pin * 0.32
    d.polygon([(cx - r * 0.85, cy + r * 0.45), (cx + r * 0.85, cy + r * 0.45), (cx, y + pin)], fill=(255, 255, 255, 255))
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255, 255))
    d.ellipse([cx - r * 0.4, cy - r * 0.4, cx + r * 0.4, cy + r * 0.4], fill=(0, 0, 0, 0))
    d.text((x + pin + 16, y - size * 0.08), text, font=font, fill=(255, 255, 255, 255))
    img.save(out)
    return out


def _tile(path: str, size: tuple[int, int]) -> Image.Image:
    tile = Image.new("RGB", size, (18, 18, 18))
    try:
        with Image.open(path) as im:
            im = im.convert("RGB")
            im.thumbnail(size)
            tile.paste(im, ((size[0] - im.width) // 2, (size[1] - im.height) // 2))
    except Exception:
        pass
    return tile


def contact_sheets(shots: list[dict], out_dir: Path, per_sheet: int = 12, cols: int = 4,
                   tile: tuple[int, int] = (360, 360)) -> list[tuple[Path, list[str]]]:
    """Grid images of shot thumbnails labelled with ids, for the vision model."""
    out_dir.mkdir(parents=True, exist_ok=True)
    font = load_font(26, "bold")
    small = load_font(18, "regular")
    sheets = []
    for b in range(0, len(shots), per_sheet):
        batch = shots[b:b + per_sheet]
        rows = (len(batch) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * tile[0] + (cols + 1) * 8, rows * tile[1] + (rows + 1) * 8), (40, 40, 40))
        d = ImageDraw.Draw(sheet)
        for i, s in enumerate(batch):
            x = 8 + (i % cols) * (tile[0] + 8)
            y = 8 + (i // cols) * (tile[1] + 8)
            sheet.paste(_tile(s["thumb"], tile), (x, y))
            d.rectangle([x, y, x + 86, y + 36], fill=(255, 214, 0))
            d.text((x + 8, y + 4), s["id"], font=font, fill=(0, 0, 0))
            info = "photo" if s["kind"] == "photo" else f"video {s['dur']:.1f}s"
            d.rectangle([x, y + tile[1] - 28, x + 12 + d.textlength(info, font=small), y + tile[1]], fill=(0, 0, 0))
            d.text((x + 6, y + tile[1] - 25), info, font=small, fill=(230, 230, 230))
        p = out_dir / f"sheet_{b // per_sheet + 1:03d}.jpg"
        sheet.save(p, "JPEG", quality=88)
        sheets.append((p, [s["id"] for s in batch]))
    return sheets


def _vertical_tile(path: str, size: tuple[int, int], subject_x: float, layout: str) -> Image.Image:
    """Approximate what the 9:16 frame will show (crop around the subject)."""
    if layout == "blur_fill":
        return _tile(path, size)
    try:
        with Image.open(path) as im:
            im = im.convert("RGB")
            w, h = im.size
            ar = size[0] / size[1]
            if w / h > ar:
                cw = h * ar
                x0 = max(0, min(w - cw, subject_x * w - cw / 2))
                im = im.crop((int(x0), 0, int(x0 + cw), h))
            else:
                ch = w / ar
                im = im.crop((0, int((h - ch) / 2), w, int((h + ch) / 2)))
            return im.resize(size, Image.Resampling.LANCZOS)
    except Exception:
        return _tile(path, size)


def used_frame(seg: dict, shot: dict) -> str:
    """A still of the moment the reel uses: a shot's thumbnail is its best frame, which may lie outside the
    part that is cut in (a clip that pans from a bridge to a river). Photos and failures: the thumbnail."""
    thumb = shot.get("thumb", "")
    src = seg.get("src") or shot.get("src")
    if shot.get("kind") != "video" or seg.get("in") is None or not src:
        return thumb
    from .config import CACHE_ROOT
    from .fx import hdr_chain
    from .util import ffmpeg_base, run, short_hash
    t = float(seg["in"]) + 0.5 * float(seg.get("dur") or 0) * float(seg.get("speed") or 1.0)
    if shot.get("t1"):
        t = min(t, float(shot["t1"]) - 0.05)
    t = max(0.0, t)
    key = "|".join([str(src), str(shot.get("sig")), f"{t:.1f}"])
    f = CACHE_ROOT / "frames" / f"{short_hash(key, 16)}.jpg"
    if f.exists():
        return str(f)
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        vf = ["scale=640:-2:flags=area"] + hdr_chain({"hdr": shot.get("hdr"), "transfer": shot.get("transfer")})
        run(ffmpeg_base() + ["-ss", f"{t:.3f}", "-i", src, "-frames:v", "1", "-vf", ",".join(vf), "-q:v", "4", f],
            timeout=40)
        return str(f) if f.exists() else thumb
    except Exception:
        return thumb


def storyboard(plan: dict, shots_by_id: dict, out: Path) -> Path:
    from concurrent.futures import ThreadPoolExecutor
    segs = plan["segments"]
    with ThreadPoolExecutor(4) as ex:  # what each cut really shows, not just the shot's best frame
        stills = list(ex.map(lambda s: used_frame(s, shots_by_id.get(s["shot_id"], {})), segs))
    cols = 8
    tw, th = 180, 320
    frame = plan.get("frame") or {}
    wide = float(frame.get("ar") or 0) > 0.6     # a wide picture with bars: show the picture, not a 9:16 crop
    if wide:
        cols, tw = 4, 372
        th = int(round(tw / float(frame["ar"])))
    rows = (len(segs) + cols - 1) // cols
    img = Image.new("RGB", (cols * (tw + 10) + 10, rows * (th + 64) + 70), (24, 24, 24))
    d = ImageDraw.Draw(img)
    title = load_font(28, "bold")
    f = load_font(15, "regular")
    fb = load_font(17, "bold")
    texts = " · ".join(f"\"{o['text']}\"" for o in plan.get("overlays", []))
    c = frame.get("canvas") or ()
    shape = (f" · horizontal {c[0]}x{c[1]}" if len(c) == 2 and c[0] > c[1]
             else f" · {frame.get('aspect')} picture" if wide and frame.get("aspect") else "")
    d.text((12, 16), f"{plan['style']} · {plan['duration']:.1f}s · {len(segs)} shots · {plan.get('tempo') or 0:.0f} BPM{shape}  {texts}"[:110],
           font=title, fill=(255, 255, 255))
    for i, s in enumerate(segs):
        x = 10 + (i % cols) * (tw + 10)
        y = 64 + (i // cols) * (th + 64)
        sh = shots_by_id.get(s["shot_id"], {})
        tile = _vertical_tile(stills[i], (tw, th), float(s.get("subject_x", 0.5)), s.get("layout", ""))
        lut = s.get("lut") or (s.get("clips") or [{}])[0].get("lut")
        if lut and Path(lut).exists():  # show the graded colour
            import numpy as np
            from .grade import apply_cube
            tile = Image.fromarray(apply_cube(np.asarray(tile.convert("RGB")), Path(lut)))
        img.paste(tile, (x, y))
        from .retime import describe
        spd = f" {describe(s, short=True)}" if describe(s) else ""
        d.text((x, y + th + 4), f"#{i + 1} {s['shot_id']} {s['dur']:.1f}s{spd}", font=fb, fill=(255, 214, 0))
        d.text((x, y + th + 26), (s.get("note") or s.get("layout", ""))[:50 if wide else 24], font=f, fill=(200, 200, 200))
        if s.get("trans_out"):
            d.text((x + tw - 14, y + th // 2), "»", font=fb, fill=(255, 214, 0))
    img.save(out, "JPEG", quality=88)
    return out
