"""Colour grading: looks, per-shot correction and LUTs.

A *look* is a target description in CIE Lab:
  Lq            luminance quantiles (1, 5, 25, 50, 75, 95, 99 %)  -> tone curve / contrast
  black, white  where pure black / white end up                    -> fade, highlight roll-off
  sh_ab, mid_ab, hi_ab   average (a, b) tint in shadows / mid-tones / highlights -> split toning
  chroma        average colourfulness                               -> saturation
  grain, vignette  finishing touches
Looks come from built-in presets or are measured from reference reels/photos (`tripshots look`).

For every shot we measure the same statistics and build a transform that moves the shot
towards the look (with a strength), after fixing exposure and white balance where the AI
says it should. The transform is baked into a 33^3 .cube LUT that ffmpeg applies (lut3d).
Shots therefore end up matching each other, not just wearing the same filter.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

from .config import HOME

LOOKS_DIR = HOME / "looks"
LUT_DIR = HOME / "luts"
QS = [1, 5, 25, 50, 75, 95, 99]
GRID = 33

PRESETS: dict[str, dict] = {
    "natural": {"desc": "Clean and true to life: balanced exposure, gentle contrast, a touch of life in the colour.",
                "Lq": [3, 8, 27, 50, 71, 90, 96], "black": 1, "white": 99, "sh_ab": [0, 0], "mid_ab": [0, 1],
                "hi_ab": [1, 3], "chroma": 22},
    "teal-orange": {"desc": "Cinematic blockbuster: teal shadows, warm orange highlights and skin, punchy contrast.",
                    "Lq": [2, 6, 24, 48, 70, 90, 96], "black": 1, "white": 98, "sh_ab": [-7, -11], "mid_ab": [1, 2],
                    "hi_ab": [7, 16], "chroma": 25,
                    "hue": [[140, 30, 40, 0.85], [100, 18, 12, 0.9], [60, 22, -4, 1.15], [265, 35, -30, 1.05]]},
    "golden-hour": {"desc": "Warm, glowing sunset light everywhere; soft highlights, honeyed mid-tones.",
                    "Lq": [4, 9, 28, 52, 72, 89, 95], "black": 3, "white": 97, "sh_ab": [3, 7], "mid_ab": [5, 13],
                    "hi_ab": [8, 20], "chroma": 27,
                    "hue": [[140, 30, -18, 0.9], [60, 25, 0, 1.15], [275, 35, -18, 0.85]]},
    "warm-film": {"desc": "Analog film: lifted blacks, rolled-off highlights, warm cast, a little grain.",
                  "Lq": [9, 13, 30, 51, 70, 86, 92], "black": 8, "white": 94, "sh_ab": [2, 5], "mid_ab": [3, 7],
                  "hi_ab": [5, 13], "chroma": 19, "grain": 5, "vignette": True,
                  "hue": [[140, 30, -15, 0.8], [275, 35, -15, 0.85], [60, 25, 0, 1.08]]},
    "moody": {"desc": "Dark and cinematic: deep shadows, cool tones, muted colours.",
              "Lq": [2, 5, 18, 37, 57, 80, 90], "black": 1, "white": 93, "sh_ab": [-4, -9], "mid_ab": [-1, -3],
              "hi_ab": [2, 5], "chroma": 15, "vignette": True,
              "hue": [[140, 30, 20, 0.7], [95, 20, 0, 0.75], [265, 35, 0, 1.0]]},
    "nordic": {"desc": "Cool, airy and calm: soft contrast, blue-grey palette, gentle desaturation.",
               "Lq": [7, 12, 31, 52, 70, 88, 94], "black": 5, "white": 97, "sh_ab": [-3, -8], "mid_ab": [-2, -5],
               "hi_ab": [-1, -3], "chroma": 14,
               "hue": [[140, 30, 15, 0.7], [60, 25, 0, 0.85], [95, 20, 0, 0.7]]},
    "vivid": {"desc": "Bright, saturated travel-brochure colour: blue skies, rich greens, clean whites.",
              "Lq": [2, 7, 28, 53, 75, 93, 98], "black": 1, "white": 99, "sh_ab": [0, -3], "mid_ab": [0, 0],
              "hi_ab": [1, 4], "chroma": 33,
              "hue": [[265, 35, -5, 1.2], [140, 30, 5, 1.15], [200, 25, 0, 1.15]]},
    "faded-matte": {"desc": "Soft pastel matte: flat lifted blacks, low contrast, light and dreamy.",
                    "Lq": [14, 18, 33, 51, 67, 82, 88], "black": 13, "white": 92, "sh_ab": [2, 2], "mid_ab": [2, 5],
                    "hi_ab": [3, 8], "chroma": 15, "grain": 3,
                    "hue": [[140, 30, 15, 0.75], [275, 35, -12, 0.85]]},
}


# ------------------------------------------------------------------ stats
def _lab(rgb_u8: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(rgb_u8.astype(np.float32) / 255.0, cv2.COLOR_RGB2LAB)


def measure(images: list[np.ndarray]) -> dict:
    """Look statistics of one or more RGB uint8 images.

    Tints are read from *near-neutral* pixels (greys, whites, blacks, concrete, clouds) in each
    tonal zone: that is where a grade's colour shows, while a blue sky or a red wall is content."""
    labs = []
    for im in images:
        h, w = im.shape[:2]
        f = min(1.0, 400 / max(h, w))
        small = cv2.resize(im, (max(1, int(w * f)), max(1, int(h * f))), interpolation=cv2.INTER_AREA) if f < 1 else im
        lab = _lab(small).reshape(-1, 3)
        # drop letterbox / pure black borders
        labs.append(lab[lab[:, 0] > 0.5] if (lab[:, 0] > 0.5).mean() > 0.5 else lab)
    lab = np.concatenate(labs)
    L, a, b = lab[:, 0], lab[:, 1], lab[:, 2]
    C = np.sqrt(a ** 2 + b ** 2)
    lq = np.percentile(L, QS)

    def ab_where(sel):
        # the least-saturated 35 % of the zone (at most chroma 22) carries the grade tint
        if sel.sum() < 30:
            return [0.0, 0.0]
        lim = min(22.0, float(np.percentile(C[sel], 35)) + 1e-3)
        n = sel & (C <= lim)
        if n.sum() < 20:
            n = sel
        return [round(float(np.median(a[n])), 2), round(float(np.median(b[n])), 2)]
    neutral = (C < 12) & (L > 15) & (L < 95)
    wb = [round(float(np.median(a[neutral])), 2), round(float(np.median(b[neutral])), 2)] \
        if neutral.sum() > 0.02 * len(L) else [0.0, 0.0]
    return {"Lq": [round(float(v), 2) for v in lq], "black": round(float(lq[0]), 2), "white": round(float(lq[-1]), 2),
            "sh_ab": ab_where(L < 30), "mid_ab": ab_where((L >= 30) & (L <= 70)), "hi_ab": ab_where(L > 70),
            "wb_ab": wb, "chroma": round(float(np.sqrt(np.mean(C ** 2))), 2)}


def look_from_images(images: list[np.ndarray], name: str, desc: str = "") -> dict:
    st = measure(images)
    st.update({"desc": desc or f"Measured from {len(images)} reference frame(s).", "name": name})
    # grain / vignette: estimate from the references
    st["vignette"] = _has_vignette(images)
    return st


def _has_vignette(images) -> bool:
    vals = []
    for im in images:
        g = cv2.cvtColor(im, cv2.COLOR_RGB2GRAY).astype(np.float32)
        h, w = g.shape
        c = g[h // 4: 3 * h // 4, w // 4: 3 * w // 4].mean()
        corners = np.mean([g[: h // 8, : w // 8].mean(), g[: h // 8, -w // 8:].mean(),
                           g[-h // 8:, : w // 8].mean(), g[-h // 8:, -w // 8:].mean()])
        vals.append(corners / max(c, 1))
    return bool(np.median(vals) < 0.72) if vals else False


# ------------------------------------------------------------- looks I/O
def list_looks() -> dict[str, dict]:
    out = {k: {**v, "name": k, "builtin": True} for k, v in PRESETS.items()}
    if LOOKS_DIR.exists():
        for p in sorted(LOOKS_DIR.glob("*.json")):
            try:
                out[p.stem] = {**json.loads(p.read_text()), "name": p.stem, "builtin": False}
            except Exception:
                pass
    return out


def get_look(name: str | None) -> dict | None:
    if not name or name in ("none", "off"):
        return None
    looks = list_looks()
    if name not in looks:
        p = Path(name).expanduser()
        if p.suffix == ".json" and p.exists():
            return json.loads(p.read_text())
        raise KeyError(f"unknown look '{name}'. Available: {', '.join(looks)}")
    return looks[name]


def save_look(look: dict, name: str) -> Path:
    LOOKS_DIR.mkdir(parents=True, exist_ok=True)
    p = LOOKS_DIR / f"{name}.json"
    p.write_text(json.dumps({k: v for k, v in look.items() if k != "builtin"}, indent=2))
    return p


# ------------------------------------------------------------ transform
def _smooth(x, e0, e1):
    t = np.clip((x - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


def _hue_weight(h, C, center, width):
    d = np.angle(np.exp(1j * np.radians(h - center)), deg=True)
    return np.exp(-0.5 * (d / width) ** 2) * _smooth(C, 3, 14)


def build_transform(src: dict, look: dict, strength: float = 0.8, notes: dict | None = None):
    """Return f(rgb float 0..1 array [...,3]) -> graded rgb, for one shot.

    Order (like a colourist's node tree): exposure -> white balance -> tone curve -> saturation
    -> hue moves (e.g. greens toward teal) -> split-tone tints per zone -> highlight protection."""
    notes = notes or {}
    s = float(np.clip(strength, 0, 1))
    keep = bool(notes.get("keep_mood"))
    s_tone = s * (0.5 if keep else 1.0)
    s_col = s * (0.6 if keep else 1.0)
    stops = float(np.clip(notes.get("exposure", 0.0) or 0.0, -1.5, 1.5))
    # guard: if the bright parts are already bright, lifting exposure only greys out a dark
    # background (low-key shots: a lit subject in front of shadow is intentional)
    hi = float(src["Lq"][5])
    if stops > 0 and hi > 70:
        stops = min(stops, max(0.0, (88 - hi) / 60))
    wb_mode = notes.get("wb") or "keep"

    # tone curve: source quantiles -> look quantiles, monotone. Never move a tone more than
    # ~18 L units: a reference full of night shots must not turn a bright beach into dusk.
    sq = np.array(src["Lq"], np.float64)
    if stops:  # quantiles after the exposure change (approx. in L)
        sq = np.clip(sq + stops * 12 * np.sin(np.pi * np.clip(sq, 0, 100) / 100) ** 0.5, 0, 100)
    tq = np.array(look["Lq"], np.float64)
    # adopt the look's contrast shape fully, but its overall brightness only halfway: a sunny
    # beach stays sunny under a dark look, it just gets the look's contrast and colour
    tq = sq[3] + (tq - tq[3]) + (tq[3] - sq[3]) * 0.5
    if keep:  # shots whose own light is the story: half of the contrast change, no brightness change
        tq = sq + ((tq - tq[3]) - (sq - sq[3])) * 0.5
    # tones move roughly like exposure: a dark tone can only be lifted a little (L 10 -> 15, not
    # 28) so a black background stays black; a bright tone can only be pulled down a little
    up = np.minimum(18, 0.5 * sq + 1)
    down = np.minimum(14, 0.3 * (100 - sq) + 1)
    tq = sq + np.clip(tq - sq, -down, up)
    xp = np.concatenate([[0.0], sq, [100.0]])
    blk = float(np.clip(float(look.get("black", 1)), 0, 20))
    wht = float(np.clip(float(look.get("white", 99)), 85, 100))
    fp = np.concatenate([[blk], tq, [wht]])
    for i in range(1, len(xp)):
        xp[i] = max(xp[i], xp[i - 1] + 0.5)
        fp[i] = max(fp[i], fp[i - 1] + 0.3)
    xp, fp = np.clip(xp, 0, 130), np.clip(fp, 0, 100)

    src_ch = max(5.0, float(src["chroma"]))
    c_scale = float(np.clip((float(look["chroma"]) / src_ch) ** 0.5, 0.75, 1.4))
    c_scale = 1 + (c_scale - 1) * s_col

    # white balance: remove the shot's own cast (measured on neutral pixels)
    wb = np.array(src.get("wb_ab", [0, 0]), np.float32)
    k = {"neutralize": 0.85, "keep": 0.3}.get(wb_mode, 0.3) * (0 if keep else 1)
    wb_shift = -wb * k

    def tint(key):
        return np.array(look.get(key, [0, 0]), np.float32) * s_col
    t_sh, t_mid, t_hi = tint("sh_ab"), tint("mid_ab"), tint("hi_ab")
    hue_ops = [(float(c), float(w), float(sh) * s_col, 1 + (float(m) - 1) * s_col)
               for c, w, sh, m in look.get("hue", [])]

    def f(rgb: np.ndarray) -> np.ndarray:
        x = np.clip(rgb, 0, 1).astype(np.float32)
        if stops:
            lin = np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4) * (2 ** stops)
            lin = lin / (1 + np.clip(lin - 0.8, 0, None))  # soft shoulder: no hard clipping
            x = np.where(lin <= 0.0031308, lin * 12.92, 1.055 * np.clip(lin, 0, None) ** (1 / 2.4) - 0.055)
            x = np.clip(x, 0, 1)
        lab = cv2.cvtColor(x.reshape(-1, 1, 3), cv2.COLOR_RGB2LAB).reshape(-1, 3)
        L, ab = lab[:, 0], lab[:, 1:] + wb_shift
        L2 = np.interp(L, xp, fp).astype(np.float32)
        L = L + (L2 - L) * s_tone
        ab = ab * c_scale
        if hue_ops:
            C = np.hypot(ab[:, 0], ab[:, 1])
            h = np.degrees(np.arctan2(ab[:, 1], ab[:, 0]))
            dh = np.zeros_like(h)
            m = np.ones_like(h)
            for c, w, sh, mul in hue_ops:
                wt = _hue_weight(h, C, c, w)
                dh += wt * sh
                m *= 1 + (mul - 1) * wt
            h2 = np.radians(h + dh)
            C2 = C * m
            ab = np.stack([C2 * np.cos(h2), C2 * np.sin(h2)], 1).astype(np.float32)
        w_sh = 1 - _smooth(L, 20, 50)
        w_hi = _smooth(L, 55, 88)
        w_mid = np.clip(1 - w_sh - w_hi, 0, 1)
        # split-tone tints colour the greys/whites/shadows; saturated colours (a blue sky,
        # a red jacket) take less of it so skies never turn purple
        protect = (1 - 0.65 * _smooth(np.hypot(ab[:, 0], ab[:, 1]), 8, 40))[:, None]
        ab = ab + protect * (w_sh[:, None] * t_sh + w_mid[:, None] * t_mid + w_hi[:, None] * t_hi)
        ab = ab * (1 - 0.6 * _smooth(L, 93, 100)[:, None])   # clean whites
        ab = ab * _smooth(L, 0, 6)[:, None]                  # clean blacks
        out = cv2.cvtColor(np.concatenate([L[:, None], ab], 1).reshape(-1, 1, 3).astype(np.float32),
                           cv2.COLOR_LAB2RGB).reshape(rgb.shape)
        return np.clip(out, 0, 1)
    return f


# -------------------------------------------------------------- LUTs
def write_cube(f, path: Path, size: int = GRID) -> Path:
    r = np.linspace(0, 1, size, dtype=np.float32)
    # .cube order: red changes fastest, then green, then blue
    B, G, R = np.meshgrid(r, r, r, indexing="ij")
    grid = np.stack([R, G, B], -1).reshape(-1, 3)
    out = f(grid)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as fh:
        fh.write(f'TITLE "tripshots"\nLUT_3D_SIZE {size}\nDOMAIN_MIN 0 0 0\nDOMAIN_MAX 1 1 1\n')
        fh.write("\n".join(f"{a:.6f} {b:.6f} {c:.6f}" for a, b, c in out))
        fh.write("\n")
    return path


def shot_lut(src_stats: dict, look: dict, strength: float, notes: dict | None) -> Path:
    key = hashlib.sha1(json.dumps(["g5", src_stats, {k: look.get(k) for k in ("Lq", "black", "white", "sh_ab", "mid_ab", "hue",
                                                                        "hi_ab", "chroma")}, round(strength, 3),
                                   notes or {}], sort_keys=True, default=str).encode()).hexdigest()[:16]
    p = LUT_DIR / f"{key}.cube"
    if not p.exists():
        write_cube(build_transform(src_stats, look, strength, notes), p)
    return p


def apply_to_image(rgb_u8: np.ndarray, f) -> np.ndarray:
    """Grade an image directly (photos, previews). Uses a LUT internally for speed."""
    size = GRID
    r = np.linspace(0, 1, size, dtype=np.float32)
    B, G, R = np.meshgrid(r, r, r, indexing="ij")
    lut = f(np.stack([R, G, B], -1).reshape(-1, 3)).reshape(size, size, size, 3)  # [b][g][r]
    x = rgb_u8.astype(np.float32) / 255.0 * (size - 1)
    i0 = np.clip(np.floor(x).astype(np.int32), 0, size - 2)
    d = x - i0
    ri, gi, bi = i0[..., 0], i0[..., 1], i0[..., 2]
    dr, dg, db = d[..., 0:1], d[..., 1:2], d[..., 2:3]
    out = np.zeros(rgb_u8.shape, np.float32)
    for ob in (0, 1):
        wb = db if ob else 1 - db
        for og in (0, 1):
            wg = dg if og else 1 - dg
            for orr in (0, 1):
                wr = dr if orr else 1 - dr
                out += lut[bi + ob, gi + og, ri + orr] * (wb * wg * wr)
    return (np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8)


# --------------------------------------------------------- AI notes per shot
NOTES_FILE = HOME / "library" / "grade_notes.json"

GRADE_PROMPT = """You are a professional colourist grading an Instagram travel reel.
The attached contact sheet shows the chosen shots, each labelled with an id.
Measured stats per shot (L = lightness 0-100 median, cast = mid-tone a/b tint: +a magenta, -a green, +b warm/yellow, -b blue):
{table}

For EACH shot decide what a good colourist would do before applying the reel's look:
- "light": golden | blue_hour | midday | overcast | night | indoor | snow | underwater | mixed
- "exposure": stops to add (-1.0..1.0). 0 if it is fine (most shots). Only raise it when the MAIN SUBJECT itself is too dark (+0.2..0.6). A dark or black background behind a well-lit subject is intentional: 0. Blown skies -0.2..-0.4. Night shots stay dark.
- "wb": "neutralize" if the cast is an error (camera white balance off, green fluorescent, blue phone shadow) or "keep" if the tint is the light itself (sunset, blue hour, neon, snow at dusk)
- "keep_mood": true for shots whose own light IS the story (sunset, blue hour, night city, fog) so the look is applied gently
{look_q}
Reply with JSON only:
{{{look_key}"shots": [{{"id": "S001", "light": "...", "exposure": 0.0, "wb": "keep", "keep_mood": false}}]}}
"""

LOOK_Q = """
Also choose the reel's look from: {looks}.
Pick what flatters THIS footage overall (e.g. lush greens and blue water -> vivid or natural; warm desert/sunsets -> golden-hour or teal-orange; misty mountains/rain -> moody or nordic; city/people -> teal-orange or warm-film).
"""


def _load_notes() -> dict:
    try:
        return json.loads(NOTES_FILE.read_text())
    except Exception:
        return {}


def _save_notes(d: dict) -> None:
    NOTES_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = NOTES_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(d))
    tmp.replace(NOTES_FILE)


def heuristic_notes(st: dict) -> dict:
    med = st["Lq"][3]
    a, b = st.get("wb_ab", [0, 0])
    hi_b = st["hi_ab"][1]
    exposure = 0.0
    if med < 35:
        exposure = min(0.7, (42 - med) / 25)
    elif med > 72:
        exposure = -min(0.4, (med - 65) / 40)
    night = med < 20
    warm_light = b > 7 and hi_b > 9          # sunset / golden hour
    blue_light = b < -7 and med < 55          # blue hour, dusk
    green_cast = a < -4
    keep = warm_light or blue_light or night
    return {"light": "night" if night else "golden" if warm_light else "blue_hour" if blue_light else "mixed",
            "exposure": round(exposure * (0.3 if night else 1), 2),
            "wb": "neutralize" if green_cast or (abs(a) + abs(b) > 6 and not keep) else "keep",
            "keep_mood": bool(keep), "source": "heuristic"}


def shot_stats(shot: dict) -> dict:
    im = cv2.imread(str(shot["thumb"]))
    if im is None:
        return measure([np.full((8, 8, 3), 128, np.uint8)])
    return measure([cv2.cvtColor(im, cv2.COLOR_BGR2RGB)])


def ai_notes(shots: list[dict], stats: dict, backend, work: Path, choose_look: bool):
    """Per-shot grading decisions from the vision model (cached forever per shot)."""
    from . import library as lib
    from .ai import extract_json
    from .text import contact_sheets
    from .util import log
    cache = _load_notes()
    keys = {s["id"]: lib.shot_key(s) for s in shots}
    notes = {i: cache[k] for i, k in keys.items() if k in cache}
    todo = [s for s in shots if s["id"] not in notes]
    look_choice = None
    if backend is None:
        return {s["id"]: notes.get(s["id"]) or heuristic_notes(stats[s["id"]]) for s in shots}, None
    look_key = "_look:" + hashlib.sha1("|".join(sorted(keys.values())).encode()).hexdigest()[:16]
    if choose_look and look_key in cache:
        look_choice = tuple(cache[look_key])
        choose_look = False
    if not todo and choose_look:
        todo = shots[:12]  # need a sheet to pick the look anyway
    if todo:
        log(f"AI colourist: {len(todo)} shot(s) -> {backend.name}")
    looks = ", ".join(f"{k} ({v['desc']})" for k, v in PRESETS.items())
    for n, (sheet, ids) in enumerate(contact_sheets(todo, work / "grade_sheets", per_sheet=12)):
        table = "\n".join(f"{i}: L={stats[i]['Lq'][3]:.0f} (5%={stats[i]['Lq'][1]:.0f}, 95%={stats[i]['Lq'][5]:.0f}), "
                          f"cast a={stats[i]['mid_ab'][0]:+.0f} b={stats[i]['mid_ab'][1]:+.0f}, "
                          f"chroma={stats[i]['chroma']:.0f}" for i in ids)
        ask_look = choose_look and n == 0
        prompt = GRADE_PROMPT.format(table=table, look_q=LOOK_Q.format(looks=looks) if ask_look else "",
                                     look_key='"look": "<name>", "why": "<one sentence>", ' if ask_look else "")
        try:
            data = extract_json(backend.ask(prompt, [sheet], max_tokens=2500))
            if ask_look and isinstance(data, dict) and data.get("look") in PRESETS:
                look_choice = (data["look"], str(data.get("why", "")))
                cache[look_key] = list(look_choice)
            rows = data.get("shots", []) if isinstance(data, dict) else data
            for d in rows or []:
                i = str(d.get("id", "")).upper()
                if i in keys:
                    v = {"light": str(d.get("light", "mixed")),
                         "exposure": float(np.clip(float(d.get("exposure") or 0), -1, 1)),
                         "wb": "neutralize" if d.get("wb") == "neutralize" else "keep",
                         "keep_mood": bool(d.get("keep_mood")), "source": backend.name}
                    notes[i] = v
                    cache[keys[i]] = v
        except Exception as e:
            log(f"  colourist sheet {sheet.name} failed ({e}); using measurements")
    _save_notes(cache)
    return {s["id"]: notes.get(s["id"]) or heuristic_notes(stats[s["id"]]) for s in shots}, look_choice


# ----------------------------------------------------------- plan grading
def _plan_shot_ids(plan: dict) -> list[str]:
    ids = []
    for seg in plan["segments"]:
        for c in (seg.get("clips") or [seg]):
            if c.get("shot_id") and c["shot_id"] not in ids:
                ids.append(c["shot_id"])
    return ids


def auto_look(stats: list[dict]) -> str:
    """No AI: pick a preset from the footage's overall character."""
    b = np.median([s["mid_ab"][1] for s in stats])
    ch = np.median([s["chroma"] for s in stats])
    med = np.median([s["Lq"][3] for s in stats])
    if b > 8:
        return "golden-hour"
    if med < 35:
        return "moody"
    if ch < 12:
        return "nordic" if b < 0 else "warm-film"
    return "vivid" if ch < 20 else "natural"


def grade_plan(plan: dict, by_id: dict, cfg: dict, backend, work: Path) -> dict | None:
    """Attach a per-shot LUT to every segment / panel clip. Returns the grade summary."""
    from .util import log
    name = str(cfg.get("look") or "auto")
    if name in ("none", "off", "false", "False"):
        return None
    strength = float(cfg.get("strength", 0.8))
    ids = [i for i in _plan_shot_ids(plan) if i in by_id]
    stats = {i: shot_stats(by_id[i]) for i in ids}
    use_ai = cfg.get("ai", True) and backend is not None
    notes, choice = ai_notes([by_id[i] for i in ids], stats, backend if use_ai else None, work, name == "auto")
    why = ""
    if name == "auto":
        if choice:
            name, why = choice
        else:
            name = auto_look(list(stats.values()))
            why = "picked from the footage's overall colour"
    look = get_look(name)
    luts = {i: str(shot_lut(stats[i], look, strength, {k: notes[i].get(k) for k in ("exposure", "wb", "keep_mood")}))
            for i in ids}
    for seg in plan["segments"]:
        for c in (seg.get("clips") or [seg]):
            if c.get("shot_id") in luts:
                c["lut"] = luts[c["shot_id"]]
                c["grade_note"] = notes[c["shot_id"]].get("light", "")
    g = {"look": name, "strength": strength, "why": why, "grain": look.get("grain", 0),
         "vignette": bool(look.get("vignette"))}
    plan["grade"] = g
    log(f"grade: look '{name}' at {int(strength * 100)}%" + (f" ({why})" if why else "")
        + f", {sum(1 for i in ids if notes[i].get('keep_mood'))} shot(s) keep their own light")
    return g


# ---------------------------------------------------------- previews
def before_after(plan: dict, by_id: dict, out: Path, max_shots: int = 8) -> Path | None:
    from PIL import Image, ImageDraw
    from .text import load_font
    rows = []
    for seg in plan["segments"]:
        for c in (seg.get("clips") or [seg]):
            if c.get("lut") and c.get("shot_id") in by_id and c["shot_id"] not in [r[0] for r in rows]:
                rows.append((c["shot_id"], c["lut"]))
    rows = rows[:max_shots]
    if not rows:
        return None
    tw, th = 360, 240
    sheet = Image.new("RGB", (tw * 2 + 24, len(rows) * (th + 8) + 52), (24, 24, 24))
    d = ImageDraw.Draw(sheet)
    font = load_font(22, "bold")
    d.text((8, 12), "before", font=font, fill=(220, 220, 220))
    d.text((tw + 16, 12), f"after: {plan.get('grade', {}).get('look', '')}", font=font, fill=(255, 214, 0))
    for r, (sid, lut) in enumerate(rows):
        im = cv2.cvtColor(cv2.imread(by_id[sid]["thumb"]), cv2.COLOR_BGR2RGB)
        h, w = im.shape[:2]
        f = min(tw / w, th / h)
        im = cv2.resize(im, (int(w * f), int(h * f)), interpolation=cv2.INTER_AREA)
        after = apply_cube(im, Path(lut))
        y = 44 + r * (th + 8)
        for k, a in enumerate((im, after)):
            sheet.paste(Image.fromarray(a), (8 + k * (tw + 8) + (tw - a.shape[1]) // 2, y + (th - a.shape[0]) // 2))
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, "JPEG", quality=88)
    return out


def read_cube(path: Path) -> np.ndarray:
    vals, size = [], GRID
    for line in Path(path).read_text().splitlines():
        t = line.strip().split()
        if not t or t[0].startswith("#") or t[0] == "TITLE" or t[0].startswith("DOMAIN"):
            continue
        if t[0] == "LUT_3D_SIZE":
            size = int(t[1])
            continue
        vals.append([float(x) for x in t[:3]])
    return np.array(vals, np.float32).reshape(size, size, size, 3)


def apply_cube(rgb_u8: np.ndarray, path: Path) -> np.ndarray:
    lut = read_cube(path)
    table = lut
    return _apply_table(rgb_u8, table)


def _apply_table(rgb_u8, lut):
    size = lut.shape[0]
    x = rgb_u8.astype(np.float32) / 255.0 * (size - 1)
    i0 = np.clip(np.floor(x).astype(np.int32), 0, size - 2)
    d = x - i0
    ri, gi, bi = i0[..., 0], i0[..., 1], i0[..., 2]
    dr, dg, db = d[..., 0:1], d[..., 1:2], d[..., 2:3]
    out = np.zeros(rgb_u8.shape, np.float32)
    for ob in (0, 1):
        wb = db if ob else 1 - db
        for og in (0, 1):
            wg = dg if og else 1 - dg
            for orr in (0, 1):
                wr = dr if orr else 1 - dr
                out += lut[bi + ob, gi + og, ri + orr] * (wb * wg * wr)
    return (np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8)


def finish_chain(grade: dict | None) -> list[str]:
    """ffmpeg filters for the look's finishing touches (grain, vignette)."""
    if not grade:
        return []
    f = []
    if grade.get("vignette"):
        f.append("vignette=angle=PI/5")
    g = int(grade.get("grain") or 0)
    if g:
        f.append(f"noise=c0s={min(g, 12)}:c0f=t+u")
    return f


# ---------------------------------------------------------- reference looks
def _frames_from(path: Path, n: int = 16) -> list[np.ndarray]:
    from .util import ffprobe, run, ffmpeg_base
    ext = path.suffix.lower()
    if ext in (".jpg", ".jpeg", ".png", ".webp", ".heic", ".tif", ".tiff"):
        from .popout import load_photo
        return [load_photo(path, max_side=1200)[0]]
    from .fx import hdr_chain
    from .media import probe_video
    try:
        info = probe_video(path)
    except Exception:
        return []
    dur = float(info.get("duration") or ffprobe(path).get("format", {}).get("duration", 0) or 0)
    if dur <= 0:
        return []
    vf = ",".join(hdr_chain(info) + ["scale=360:-2"])
    out = []
    import subprocess
    for k in range(n):
        t = 0.4 + (dur - 0.8) * (k + 0.5) / n
        proc = subprocess.run(ffmpeg_base() + ["-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1",
                                                "-vf", vf, "-f", "image2pipe", "-vcodec", "png", "-"],
                              capture_output=True)
        if proc.returncode == 0 and proc.stdout:
            im = cv2.imdecode(np.frombuffer(proc.stdout, np.uint8), cv2.IMREAD_COLOR)
            if im is not None:
                out.append(cv2.cvtColor(im, cv2.COLOR_BGR2RGB))
    return out


LOOK_PROMPT = """These frames come from reference Instagram reels whose colour grade the user wants to copy.
Measured: tone quantiles L(1..99%)={Lq}, shadow tint a/b={sh}, mid tint={mid}, highlight tint={hi}, chroma={chroma}.
Describe the grade in one short sentence a non-editor understands (e.g. "teal shadows, warm skin, crushed blacks, muted greens").
Also say if the colour mostly comes from the *scenes* (e.g. every frame is a sunset) rather than from grading.
Reply JSON only: {{"desc": "...", "scene_driven": false, "grain": 0-8, "vignette": true|false}}"""


def look_from_refs(refs: list[str], name: str, backend=None, cookies_browser=None, cookies_file=None) -> Path:
    from .fetch import fetch_video
    from .util import ReelError, log
    work = HOME / "learn" / f"look-{name}"
    work.mkdir(parents=True, exist_ok=True)
    frames = []
    for r in refs:
        p = Path(r).expanduser()
        if p.is_dir():
            items = [q for q in sorted(p.rglob("*")) if q.suffix.lower() in
                     (".jpg", ".jpeg", ".png", ".heic", ".mp4", ".mov", ".m4v", ".webp")][:40]
        elif p.exists():
            items = [p]
        elif r.startswith("http"):
            log(f"downloading {r}")
            items = [fetch_video(r, work / "downloads", cookies_browser, cookies_file)]
        else:
            raise ReelError(f"not a file, folder or URL: {r}")
        for q in items:
            got = _frames_from(Path(q), 16 if len(items) == 1 else 4)
            log(f"  {Path(q).name}: {len(got)} frame(s)")
            frames += got
    if not frames:
        raise ReelError("could not read any frames from the references")
    look = look_from_images(frames, name)
    # save a reference sheet so the user (and the AI) can see what was measured
    tiles = [cv2.resize(f, (180, int(180 * f.shape[0] / f.shape[1]))) for f in frames[:24]]
    hmax = max(t.shape[0] for t in tiles)
    tiles = [cv2.copyMakeBorder(t, 0, hmax - t.shape[0], 0, 0, cv2.BORDER_CONSTANT) for t in tiles]
    rows = [np.hstack(tiles[i:i + 6] + [np.zeros_like(tiles[0])] * (6 - len(tiles[i:i + 6])))
            for i in range(0, len(tiles), 6)]
    sheet_p = work / "reference.jpg"
    cv2.imwrite(str(sheet_p), cv2.cvtColor(np.vstack(rows), cv2.COLOR_RGB2BGR))
    if backend is not None:
        from .ai import extract_json
        try:
            d = extract_json(backend.ask(LOOK_PROMPT.format(Lq=[round(v) for v in look["Lq"]], sh=look["sh_ab"],
                                                            mid=look["mid_ab"], hi=look["hi_ab"],
                                                            chroma=round(look["chroma"])), [sheet_p], max_tokens=400))
            look["desc"] = str(d.get("desc") or look["desc"])
            look["grain"] = int(np.clip(float(d.get("grain") or 0), 0, 8))
            look["vignette"] = bool(d.get("vignette", look.get("vignette")))
            if d.get("scene_driven"):
                # the colour is in the scenes: keep the tone shape, soften the tints
                for k in ("sh_ab", "mid_ab", "hi_ab"):
                    look[k] = [round(v * 0.5, 2) for v in look[k]]
                look["desc"] += " (tints softened: they came from the scenes)"
        except Exception as e:
            log(f"AI look description failed ({e}); saved the measured look")
    look["refs"] = refs
    p = save_look(look, name)
    log(f"look saved: {p} - {look['desc']}")
    return p


def grade_image(rgb: np.ndarray, look_name: str, strength: float = 0.8, notes: dict | None = None) -> np.ndarray:
    st = measure([rgb])
    if look_name == "auto":
        look_name = auto_look([st])
    n = notes or heuristic_notes(st)
    return apply_to_image(rgb, build_transform(st, get_look(look_name), strength,
                                               {k: n.get(k) for k in ("exposure", "wb", "keep_mood")}))


# ---------------------------------------------------------- grade files
def grade_files(paths: list[Path], look_name: str, strength: float, out_dir: Path, backend=None,
                preview: bool = True) -> list[Path]:
    """Export graded copies of photos and videos (outside a reel)."""
    from .fx import hdr_chain
    from .media import find_media, probe_video
    from .popout import load_photo
    from .util import ffmpeg_base, log, run
    files = find_media(paths)
    out_dir.mkdir(parents=True, exist_ok=True)
    outs, pairs = [], []
    auto = look_name == "auto"
    items = []
    for f in files:
        f = Path(f)
        if f.suffix.lower() in (".mp4", ".mov", ".m4v", ".mkv", ".avi", ".mts"):
            fr = _frames_from(f, 6)
            info = probe_video(f)
            kind = "video"
        else:
            fr = [load_photo(f, max_side=12000)[0]]
            info, kind = None, "photo"
        if not fr:
            continue
        items.append((f, kind, fr, info, measure(fr)))
    if not items:
        return []
    if auto:
        look_name = auto_look([it[4] for it in items])
        log(f"look: {look_name}")
    look = get_look(look_name)
    for f, kind, fr, info, st in items:
        notes = heuristic_notes(st)
        lut = shot_lut(st, look, strength, {k: notes.get(k) for k in ("exposure", "wb", "keep_mood")})
        if kind == "photo":
            dst = out_dir / f"{f.stem}.{look_name}.jpg"
            full = fr[0]
            graded = apply_cube(full, lut)
            cv2.imwrite(str(dst), cv2.cvtColor(graded, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 95])
            pairs.append((full, graded))
        else:
            dst = out_dir / f"{f.stem}.{look_name}.mp4"
            vf = ",".join(hdr_chain(info) + [f"lut3d=file='{lut}'"] + finish_chain(look) + ["format=yuv420p"])
            run(ffmpeg_base() + ["-i", str(f), "-vf", vf, "-c:v", "libx264", "-crf", "17", "-preset", "medium",
                                 "-c:a", "copy", "-movflags", "+faststart", str(dst)])
            pairs.append((fr[len(fr) // 2], apply_cube(fr[len(fr) // 2], lut)))
        log(f"  {f.name} -> {dst.name}  ({notes['light']}, exposure {notes['exposure']:+.2f})")
        outs.append(dst)
    if preview and pairs:
        tw = 400
        rows = []
        for a, b in pairs[:10]:
            h = int(tw * a.shape[0] / a.shape[1])
            rows.append(np.hstack([cv2.resize(a, (tw, h)), np.full((h, 8, 3), 24, np.uint8), cv2.resize(b, (tw, h))]))
        wmax = max(r.shape[1] for r in rows)
        sheet = np.vstack([np.vstack([r, np.full((8, wmax, 3), 24, np.uint8)]) for r in rows])
        p = out_dir / f"before-after.{look_name}.jpg"
        cv2.imwrite(str(p), cv2.cvtColor(sheet, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 90])
        outs.append(p)
    return outs
