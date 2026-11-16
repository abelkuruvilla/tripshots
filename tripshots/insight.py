"""Things measured about each shot on this computer (no AI), once, and kept in the library with the shot:

- text_room   how busy each band of the upright frame is (upper, center, lower: 0 calm .. 1 busy) and the calmest,
              so a hook or a title can be put where it reads
- ocr         lines of type the text detector (reftext's PP-OCR det) finds, and `burned_in` (0..1): how much they
              look like words drawn ON the picture (captions, a watermark, an app's buttons) rather than a sign in it
- fit         whether the subjects fit an upright 9:16, a 4:5 (carousel) and a square crop of the picture
- faces       how many, the biggest (share of the frame), how frontal it is (eyes either side of the nose) and how sharp
- flat        the picture looks like flat log footage (camlog.looks_flat)
- camera      maker, model, lens, focal length, bit depth, colour transfer and primaries (file metadata)
video only (`deep`: decodes a few frames and the sound):
- open_motion how much moves in the first quarter second (a hook that opens on movement holds the thumb)
- loop        how alike the first and last frames are (0..1): a clip that can end where it began
- audio       loudness (dB), and estimates (0..1) of speech and of music in the clip's own sound

Cached per shot (library table `analysis`, key "insight:<shot key>"); `attach` puts them on shots as s["insight"].
The audio estimates are signal heuristics, not a trained classifier: they nudge choices, they never decide alone.
"""
from __future__ import annotations

import json
import math
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np

from . import library as lib
from .util import ffmpeg_base, log

VERSION = 1
STRIPS = lib.LIB_DIR / "strips"


# ---------------------------------------------------------------- frames
def frame_at(src: str, t: float, width: int = 320, hdr: dict | None = None) -> np.ndarray | None:
    """One RGB frame of a video at t seconds (cached as a small jpg); `hdr` {hdr, transfer}: tone-mapped to SDR."""
    from .fx import hdr_chain
    from .util import short_hash
    STRIPS.mkdir(parents=True, exist_ok=True)
    # Same-quote nesting inside an f-string is a 3.12+ syntax; CI still runs 3.11.
    hdr_on = bool((hdr or {}).get("hdr"))
    f = STRIPS / f"{short_hash(f'{src}|{t:.2f}|{width}|{hdr_on}', 16)}.jpg"
    if not f.exists():
        vf = ",".join(hdr_chain(hdr or {}) + [f"scale={width}:-2", "format=yuvj420p"])
        try:
            subprocess.run(ffmpeg_base() + ["-ss", f"{max(0.0, t):.3f}", "-i", str(src), "-frames:v", "1",
                                            "-vf", vf, "-q:v", "4", str(f)],
                           capture_output=True, timeout=40)
        except subprocess.TimeoutExpired:
            return None
    im = cv2.imread(str(f))
    return cv2.cvtColor(im, cv2.COLOR_BGR2RGB) if im is not None else None


def moments(shot: dict) -> list[float]:
    """Start, middle and end of a video shot (a little inside its edges)."""
    t0, t1 = float(shot.get("t0", 0)), float(shot.get("t1", 0))
    d = max(0.0, t1 - t0)
    return [t0 + min(0.15, d * 0.05), t0 + d / 2, max(t0, t1 - min(0.15, d * 0.05))]


def strip(shot: dict, height: int = 440) -> Path | None:
    """Three moments of a clip in one picture, for the AI: side by side for an upright clip, stacked for a wide
    one (so the strip stays near square). None for a photo or when frames can't be read."""
    if shot.get("kind") != "video" or not shot.get("src"):
        return None
    from .util import short_hash
    out = STRIPS / f"strip_{short_hash(lib.shot_key(shot), 16)}.jpg"
    if out.exists():
        return out
    fr = [frame_at(shot["src"], t, hdr=shot) for t in moments(shot)]
    if any(f is None for f in fr):
        return None
    h, w = fr[0].shape[:2]
    fr = [cv2.resize(f, (w, h)) for f in fr]
    gap = 6
    if w >= h:
        canvas = np.full((3 * h + 2 * gap, w, 3), 30, np.uint8)
        for k, f in enumerate(fr):
            canvas[k * (h + gap):k * (h + gap) + h] = f
    else:
        canvas = np.full((h, 3 * w + 2 * gap, 3), 30, np.uint8)
        for k, f in enumerate(fr):
            canvas[:, k * (w + gap):k * (w + gap) + w] = f
    STRIPS.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), cv2.cvtColor(canvas, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 85])
    return out


# ---------------------------------------------------------------- picture measurements
def upright(rgb: np.ndarray, subject_x: float = 0.5, ar: float = 9 / 16) -> np.ndarray:
    """The part of the picture an upright frame of this shape shows (cropped at the subject)."""
    h, w = rgb.shape[:2]
    if w / h <= ar:
        return rgb
    cw = int(h * ar)
    x0 = int(max(0, min(w - cw, subject_x * w - cw / 2)))
    return rgb[:, x0:x0 + cw]


def text_room(rgb: np.ndarray) -> dict:
    """Busyness (edge density, 0 calm .. 1 busy) of the upper, centre and lower bands of an upright frame."""
    g = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    g = cv2.resize(g, (180, 320), interpolation=cv2.INTER_AREA)
    e = cv2.Canny(g, 60, 160).astype(np.float32) / 255.0
    bands = {"upper": (0.13, 0.40), "center": (0.37, 0.62), "lower": (0.55, 0.75)}   # typo.BANDS, as shares
    out = {k: round(float(min(1.0, e[int(a * 320):int(b * 320)].mean() * 6)), 3) for k, (a, b) in bands.items()}
    out["calmest"] = min(("upper", "center", "lower"), key=lambda k: out[k])
    return out


def ocr(rgb: np.ndarray) -> dict:
    """Lines of type in the picture and how much they look drawn on it (0..1)."""
    from .reftext import _lines
    h, w = rgb.shape[:2]
    boxes = _lines(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    boxes = [b for b in boxes if (b[2] - b[0]) * (b[3] - b[1]) > 0.0008 * w * h]
    area = sum((b[2] - b[0]) * (b[3] - b[1]) for b in boxes) / float(w * h)
    burned = 0.0
    if boxes:
        hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
        caption_like = 0.0
        for x0, y0, x1, y1 in boxes:
            bw, bh = (x1 - x0) / w, (y1 - y0) / h
            cx, cy = (x0 + x1) / 2 / w, (y0 + y1) / 2 / h
            flat_line = bw > 2.5 * bh                        # a line of type, not a blob
            edge_band = cy < 0.2 or cy > 0.72                # where captions, titles and app bars go
            centred = abs(cx - 0.5) < 0.25 and bw > 0.18
            if not (flat_line and (edge_band or centred)):
                continue
            # drawn-on type is (almost always) white or black; a shop sign's letters are coloured
            box = hsv[y0:y1, x0:x1].reshape(-1, 3).astype(np.float32)
            v, sat = box[:, 2], box[:, 1]
            ink = np.abs(v - np.median(v)) > 40              # the letters: what stands out from the line's background
            plain = float(np.mean((sat[ink] < 50) & ((v[ink] > 200) | (v[ink] < 60)))) if ink.sum() > 20 else 0.0
            caption_like += max(0.0, min(1.0, (plain - 0.4) / 0.4))
        burned = min(1.0, 0.45 * caption_like + 3 * area * min(1.0, caption_like)) if caption_like else min(0.3, 2 * area)
    return {"lines": len(boxes), "area": round(area, 4), "burned_in": round(burned, 2)}


def fit(shot: dict) -> dict:
    """Do the subjects fit an upright (9:16), a 4:5 and a square crop of this picture?"""
    w, h = float(shot.get("w") or 1), float(shot.get("h") or 1)
    a = shot.get("ai") or {}
    boxes = [sj.get("box") for sj in (a.get("subjects") or [])[:2] if sj.get("box")] or \
        ([a["subject_box"]] if a.get("subject_box") else [])
    out = {}
    for name, ar in (("9:16", 9 / 16), ("4:5", 4 / 5), ("1:1", 1.0)):
        if w / h <= ar or not boxes:
            out[name] = True if w / h <= ar else None   # already narrow enough / nothing known
            continue
        win = ar / (w / h)                                  # the crop's width as a share of the picture's
        x0, x1 = min(b[0] for b in boxes), max(b[2] for b in boxes)
        out[name] = bool(x1 - x0 <= win * 0.96)
    return out


def faces(rgb: np.ndarray) -> dict:
    """Faces in the picture: count, the biggest one's share of the frame, how frontal (0..1) and sharp (0..1)."""
    try:
        from .people import _nets
        det, _ = _nets()
    except Exception:
        return {}
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    h, w = bgr.shape[:2]
    det.setInputSize((w, h))
    _, rows = det.detect(bgr)
    rows = [r for r in (rows if rows is not None else []) if r[14] > 0.75 and min(r[2], r[3]) >= 12]
    if not rows:
        return {"n": 0}
    r = max(rows, key=lambda r: r[2] * r[3])
    reye, leye, nose = (r[4], r[5]), (r[6], r[7]), (r[8], r[9])
    dist = math.hypot(leye[0] - reye[0], leye[1] - reye[1]) + 1e-6
    frontal = max(0.0, 1.0 - abs(nose[0] - (reye[0] + leye[0]) / 2) / (0.5 * dist))
    x, y, fw, fh = (int(max(0, v)) for v in r[:4])
    crop = cv2.cvtColor(bgr[y:y + fh, x:x + fw], cv2.COLOR_BGR2GRAY)
    sharp = min(1.0, float(cv2.Laplacian(crop, cv2.CV_64F).var()) / 300.0) if crop.size else 0.0
    return {"n": len(rows), "biggest": round(float(r[2] * r[3]) / (w * h), 4), "frontal": round(float(frontal), 2),
            "sharp": round(float(sharp), 2)}


def camera(shot: dict) -> dict:
    """The file's camera, lens and colour details."""
    from .analysis import camera_info
    out = camera_info(str(shot.get("src")), shot.get("kind", "photo"))
    if shot.get("kind") == "video":
        try:
            p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_streams", "-show_format",
                                "-of", "json", str(shot["src"])], capture_output=True, text=True, timeout=30)
            info = json.loads(p.stdout or "{}")
            vs = (info.get("streams") or [{}])[0]
            tags = {k.lower(): v for k, v in ((info.get("format") or {}).get("tags") or {}).items()}
            pix = str(vs.get("pix_fmt") or "")
            out["bit_depth"] = 10 if "10" in pix else 12 if "12" in pix else 8
            for k in ("color_transfer", "color_primaries"):
                if vs.get(k):
                    out[k.replace("color_", "")] = vs[k]
            for k, names in (("lens", ("com.apple.quicktime.camera.lens_model",)),
                             ("focal", ("com.apple.quicktime.camera.focal_length.35mm_equivalent",))):
                for n in names:
                    if tags.get(n):
                        out[k] = tags[n] if k == "lens" else round(float(tags[n]), 1)
        except Exception:
            pass
    return out


# ---------------------------------------------------------------- video only (deep)
def open_motion(shot: dict) -> float | None:
    """How much moves between the first frame and a quarter second later (0 still .. 1 a lot)."""
    t0 = float(shot.get("t0", 0)) + 0.05
    a, b = frame_at(shot["src"], t0, 160, shot), frame_at(shot["src"], t0 + 0.25, 160, shot)
    if a is None or b is None or a.shape != b.shape:
        return None
    ga, gb = (cv2.cvtColor(x, cv2.COLOR_RGB2GRAY) for x in (a, b))
    flow = cv2.calcOpticalFlowFarneback(ga, gb, None, 0.5, 3, 15, 3, 5, 1.2, 0)
    mag = float(np.median(np.linalg.norm(flow, axis=2))) / ga.shape[1]
    return round(min(1.0, mag * 20), 3)


def _dhash(rgb: np.ndarray) -> int:
    g = cv2.resize(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY), (9, 8), interpolation=cv2.INTER_AREA)
    bits = (g[:, 1:] > g[:, :-1]).flatten()
    return int("".join("1" if x else "0" for x in bits), 2)


def loop_match(shot: dict) -> float | None:
    ts = moments(shot)
    a, b = frame_at(shot["src"], ts[0], hdr=shot), frame_at(shot["src"], ts[2], hdr=shot)
    if a is None or b is None:
        return None
    return round(1 - bin(_dhash(a) ^ _dhash(b)).count("1") / 64.0, 3)


SR = 16000


def audio(shot: dict) -> dict | None:
    """Loudness and rough speech / music estimates from up to 6 s of the clip's own sound."""
    t0, t1 = float(shot.get("t0", 0)), float(shot.get("t1", 0))
    dur = min(6.0, max(0.5, t1 - t0))
    try:
        raw = subprocess.run(ffmpeg_base() + ["-ss", f"{t0:.3f}", "-t", f"{dur:.3f}", "-i", str(shot["src"]), "-vn",
                                              "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                             capture_output=True, timeout=40).stdout
    except subprocess.TimeoutExpired:
        return None
    x = np.frombuffer(raw, np.float32)
    if len(x) < SR // 4:
        return None
    rms = float(np.sqrt(np.mean(x ** 2))) + 1e-12
    db = 20 * math.log10(rms)
    if db < -55:
        return {"db": round(db, 1), "speech": 0.0, "music": 0.0}
    hop, win = 160, 1024                                  # 10 ms hops, 64 ms windows
    n = (len(x) - win) // hop
    if n < 20:
        return {"db": round(db, 1), "speech": 0.0, "music": 0.0}
    idx = np.arange(win)[None, :] + hop * np.arange(n)[:, None]
    spec = np.abs(np.fft.rfft(x[idx] * np.hanning(win)[None, :], axis=1)) ** 2 + 1e-12
    freqs = np.fft.rfftfreq(win, 1 / SR)
    band = (freqs >= 100) & (freqs <= 5000)
    sb = spec[:, band]
    # music: notes are narrow peaks standing far above the frequencies either side of them (noise, wind and
    # rumble are broad, however loud), and the same peaks carry on from one moment to the next
    from scipy.ndimage import median_filter
    prom = sb / (median_filter(sb, size=(1, 21), mode="nearest") + 1e-12)
    peaks = prom > 25
    voiced = peaks.sum(1) >= 2
    tonal = float(np.mean(voiced))
    held = float((peaks[1:] & peaks[:-1]).sum() / max(1, peaks[:-1].sum()))
    switch = float(np.mean(voiced[1:] != voiced[:-1]))   # speech flips between voiced and unvoiced all the time
    # speech: loudness rising and falling at the rate of syllables (3-8 a second), deep gaps between words
    voice = spec[:, (freqs >= 300) & (freqs <= 3400)].sum(1)
    env = np.log(voice + 1e-9)
    depth = float(np.percentile(env, 90) - np.percentile(env, 10))
    env = env - np.convolve(env, np.ones(50) / 50, mode="same")      # take out slow drifts
    m = np.abs(np.fft.rfft(env * np.hanning(len(env))))
    mf = np.fft.rfftfreq(len(env), hop / SR)
    syll = float(m[(mf >= 3) & (mf <= 8)].sum() / (m[(mf > 0.5) & (mf <= 25)].sum() + 1e-9))
    clip = lambda v: max(0.0, min(1.0, v))
    speech = clip((syll - 0.33) * 6) * clip((depth - 3) / 3) * clip((switch - 0.05) * 12)
    music = clip((tonal - 0.4) * 2) * clip((held - 0.5) * 3) * clip(1 - switch * 6)
    return {"db": round(db, 1), "speech": round(speech, 2), "music": round(music, 2)}


# ---------------------------------------------------------------- per shot
def _thumb(shot: dict) -> np.ndarray | None:
    im = cv2.imread(str(shot.get("thumb") or ""))
    if im is None:
        return None
    s = 480 / max(im.shape[:2])
    if s < 1:
        im = cv2.resize(im, (int(im.shape[1] * s), int(im.shape[0] * s)), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(im, cv2.COLOR_BGR2RGB)


def measure(shot: dict, deep: bool = True) -> dict:
    """Everything above for one shot (the video parts only with `deep`)."""
    from .camlog import looks_flat
    out: dict = {"v": VERSION}
    rgb = _thumb(shot)
    if rgb is not None:
        sx = float((shot.get("ai") or {}).get("subject_x", 0.5))
        out["text_room"] = text_room(upright(rgb, sx))
        try:
            out["ocr"] = ocr(rgb)
        except Exception:
            pass
        out["faces"] = faces(rgb)
        out["flat"] = looks_flat(rgb)
    out["fit"] = fit(shot)
    out["camera"] = camera(shot)
    if deep and shot.get("kind") == "video" and shot.get("src"):
        out["open_motion"] = open_motion(shot)
        out["loop"] = loop_match(shot)
        out["audio"] = audio(shot)
        out["deep"] = True
    return out


def _key(shot: dict) -> str:
    return f"insight:{lib.shot_key(shot)}"


def load(shots: list[dict]) -> int:
    """Put what is already measured on the shots, measuring nothing."""
    n = 0
    for s in shots:
        got = lib.get_analysis(_key(s), VERSION)
        if got:
            s["insight"] = got
            n += 1
    return n


def attach(shots: list[dict], deep: set | None = None, workers: int = 4, quiet: bool = False) -> int:
    """Put each shot's measurements on it (s["insight"]), measuring only what isn't stored yet. `deep`: ids of
    the shots whose video and sound to measure as well (None = all of them). Returns how many were measured."""
    todo = []
    for s in shots:
        want_deep = s.get("kind") == "video" and (deep is None or s["id"] in deep)
        got = lib.get_analysis(_key(s), VERSION)
        if got and (got.get("deep") or not want_deep):
            s["insight"] = got
        else:
            todo.append((s, want_deep))
    if not todo:
        return 0
    if not quiet:
        log(f"insight: measuring {len(todo)} shot(s) on this computer (text, room for titles, faces, motion, sound)")

    def one(item):
        s, d = item
        try:
            m = measure(s, d)
        except Exception as e:   # one odd file never stops the rest
            m = {"v": VERSION, "error": str(e)[:80]}
        lib.put_analysis(_key(s), VERSION, m)
        return s, m
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for s, m in ex.map(one, todo):
            s["insight"] = m
            done += 1
            if not quiet and done % 200 == 0:
                log(f"  insight {done}/{len(todo)}")
    return done


# ---------------------------------------------------------------- what the rest of the engine asks
OVERLAY_WORDS = ("text overlay", "overlay reading", "caption reading", "captioned with", "watermark", "screenshot",
                 "screen recording", "on-screen text", "subtitle", "story-style text", "app interface", "ui overlay")


def burned_in(shot: dict) -> float:
    """0..1: words drawn onto the picture (an edited export, a saved reel, a screenshot). The AI's issue, or its
    description saying so, decide; the text detector alone counts only when it is nearly sure (a white-lettered
    park sign looks much like a caption to it)."""
    a = shot.get("ai") or {}
    if "burned-in-text" in (a.get("issues") or []):
        return 1.0
    said = " ".join(str(a.get(k) or "") for k in ("description", "caption", "note")).lower()
    if any(w in said for w in OVERLAY_WORDS):
        return 0.9
    o = float(((shot.get("insight") or {}).get("ocr") or {}).get("burned_in") or 0.0)
    return o if o >= 0.9 else round(o * 0.5, 2)


def hook_bonus(shot: dict) -> float:
    """A small lift for opening a reel: movement in the first frame, a sharp frontal face, room for the hook."""
    ins = shot.get("insight") or {}
    b = 0.0
    om = ins.get("open_motion")
    if om is not None:
        b += 0.6 * min(1.0, om / 0.35)
    f = ins.get("faces") or {}
    if f.get("n") and f.get("frontal", 0) > 0.6 and f.get("sharp", 0) > 0.3:
        b += 0.4
    room = (ins.get("text_room") or {})
    if room and min(room.get("upper", 1), room.get("center", 1)) < 0.25:
        b += 0.2
    return round(b, 3)
