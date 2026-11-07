"""Clone a reference reel shot for shot with your own footage.

`tripshots clone <reel link or video> <your folders>`:
  1. the reference is cut into its shots (exact cut times, which land on its own soundtrack's beats),
     flash cuts are detected, each shot gets a frame and a motion measure
  2. the AI looks at the reference shots: what each one shows (wide landscape, aerial, close
     detail, walking POV...), how the camera moves, and every piece of on-screen text with its
     position and role (hook, location, label, closing line)
  3. the AI fills every slot with your best matching shot (with runners-up, used for variants) and
     rewrites the text for your places, keeping its format and length
  4. the plan keeps the reference's timing, its soundtrack and its colour (measured into a look),
     and renders like any other reel; a side-by-side sheet shows reference vs. clone per slot
"""
from __future__ import annotations

import json
import math
import re
import subprocess
from pathlib import Path

import cv2
import numpy as np

from .config import HOME, OUT_FPS
from .util import ReelError, ffmpeg_base, ffprobe, log, read_json, short_hash, write_json

TYPES = ["wide_landscape", "aerial", "close_detail", "person", "walking_pov", "water", "city", "road_vehicle",
         "sky", "night", "food", "wildlife", "interior", "other"]

SLOT_PROMPT = """These are the shots of a reference Instagram Reel (one frame from each, labelled R01, R02... in order).
Shot timing: {timing}
For EACH shot return:
- "type": one of {types}
- "content": what it shows in at most 8 words (e.g. "turquoise lake below snowy peaks")
- "camera": static | pan | push | handheld | drone | timelapse
- "energy": calm | medium | intense (how busy the shot feels)
- "text": the exact on-screen text in this frame ("" if none; ignore Instagram's UI, watermarks and text that is part
  of a map or graphic). Text often appears word by word or stays across several shots: when the same line
  continues over neighbouring shots, give the COMPLETE line on every shot it appears in, identically.
- "text_pos": top | center | bottom
- "text_role": hook | location | label | cta | caption
Reply with JSON only: {{"shots": [{{"id": "R01", "type": "...", "content": "...", "camera": "...", "energy": "...",
"text": "", "text_pos": "center", "text_role": "hook"}}]}}"""

MATCH_PROMPT = """You are recreating a reference Instagram Reel shot for shot with the user's own travel footage.

Reference slots (in order; dur in seconds):
{slots}

The user's shots (id, kind, usable length, AI score 1-10, tags, note, place):
{shots}

1. For every slot pick the 3 best user shots, best first. Match what the slot shows (type/content) first,
   then its camera movement and energy. A video must be at least as long as the slot (a photo always fits).
   Use each shot at most once in your FIRST choices unless there are more slots than shots. Put the most
   striking shot in R01 (it is the hook).
2. Rewrite every reference on-screen text for the user's trip, keeping its format, tone, word count and
   role (a "POV: ..." stays a POV, a place name becomes one of the user's places{places_hint}). Give 3
   alternatives per text, best first. Never invent facts the footage does not show.
Reply with JSON only:
{{"slots": [{{"id": "R01", "shots": ["S004", "S011", "S002"], "why": "..."}}],
  "texts": [{{"ref": "<reference text>", "new": ["...", "...", "..."]}}]}}"""


# ================================================================ reference analysis
def _luma_track(path: Path, w: int = 72, hist: bool = False):
    """Mean brightness and frame-to-frame change for every frame at OUT_FPS (tiny gray decode);
    with hist=True also the change of the brightness histogram (a cut changes it, a zoom doesn't)."""
    h = int(w * 16 / 9) // 2 * 2
    proc = subprocess.run(ffmpeg_base() + ["-i", str(path), "-vf", f"fps={OUT_FPS},scale={w}:{h},format=gray",
                                           "-f", "rawvideo", "-"], capture_output=True)
    a = np.frombuffer(proc.stdout, np.uint8)
    n = len(a) // (w * h)
    fr = a[: n * w * h].reshape(n, h, w).astype(np.float32)
    mean = fr.mean(axis=(1, 2))
    diff = np.r_[0, np.abs(np.diff(fr, axis=0)).mean(axis=(1, 2))]
    if not hist:
        return mean, diff
    def hists(a):
        return np.stack([np.histogram(x, 32, (0, 256))[0] for x in a]).astype(np.float32) / a[0].size
    H = hists(fr)
    top, bot = hists(fr[:, : int(h * 0.25)]), hists(fr[:, int(h * 0.82):])
    return mean, diff, {"H": H, "top": top, "bot": bot}


def _grab(path: Path, t: float, out: Path, width: int = 360) -> Path | None:
    p = subprocess.run(ffmpeg_base() + ["-ss", f"{max(0, t):.3f}", "-i", str(path), "-frames:v", "1",
                                        "-vf", f"scale={width}:-2", "-q:v", "3", str(out)], capture_output=True)
    return out if p.returncode == 0 and out.exists() else None


def analyze_reference(ref: str, work: Path, cookies: dict | None = None) -> dict:
    from .fetch import fetch_video
    p = Path(ref).expanduser()
    if not p.exists():
        if not re.match(r"https?://", ref):
            raise ReelError(f"not a file or link: {ref}")
        log(f"downloading the reference reel {ref}")
        cookies = cookies or {}
        p = fetch_video(ref, HOME / "learn" / "downloads", cookies.get("cookies_browser"), cookies.get("cookies_file"))
    key = short_hash(f"{p.resolve()}|{p.stat().st_size}", 12)
    rdir = work / f"ref_{key}"
    rdir.mkdir(parents=True, exist_ok=True)
    cached = read_json(rdir / "reference.json")
    if cached and cached.get("version") == 7:
        return cached
    info = ffprobe(p)
    dur = float(info.get("format", {}).get("duration", 0) or 0)
    if dur <= 0:
        raise ReelError(f"could not read the reference video {p.name}")
    log(f"cutting the reference into shots ({dur:.1f}s)")
    mean, diff, hs = _luma_track(p, hist=True)
    nfr = len(mean)
    H, TOP, BOT = hs["H"], hs["top"], hs["bot"]

    def jump(A, a, b):
        return float(np.abs(A[min(b, nfr - 1)] - A[max(a, 0)]).sum())
    hd = np.r_[0, np.abs(np.diff(H, axis=0)).sum(1)]
    # a cut = a one-frame jump in the brightness histogram (zoom punches and shakes barely move it),
    # or, between two similar-looking shots, a big picture change with a smaller histogram jump.
    # The top and bottom of the frame must both change, so a title card or map popping up in the
    # middle doesn't count as a cut.
    cuts = []
    for f in range(2, nfr - 2):
        if hd[f] < hd[max(1, f - 3):f + 4].max():
            continue
        mh = float(np.median(hd[max(1, f - 15):f + 15]))
        md = float(np.median(diff[max(1, f - 15):f + 15]))
        if not (hd[f] > max(0.3, 4 * mh) or (diff[f] > max(18.0, 3.2 * md) and hd[f] > max(0.12, 2.5 * mh))):
            continue
        if min(jump(TOP, f - 1, f), jump(BOT, f - 1, f)) < 0.25:
            continue
        if not cuts or f / OUT_FPS - cuts[-1] > 0.1:
            cuts.append(f / OUT_FPS)
    # dissolves: no single-frame jump, but the picture becomes a different one over ~10 frames
    wv = np.array([jump(H, f - 7, f + 7) for f in range(nfr)])
    dissolves = []
    for f in range(6, nfr - 6):
        if wv[f] < wv[max(0, f - 8):f + 9].max() or any(abs(f / OUT_FPS - c) < 0.35 for c in cuts):
            continue
        if wv[f] > max(0.25, 3 * float(np.median(wv[max(0, f - 45):f + 45]))) and \
                min(jump(TOP, f - 7, f + 7), jump(BOT, f - 7, f + 7)) >= 0.15:
            dissolves.append(f / OUT_FPS)
    cuts = sorted(cuts + dissolves)
    # snap each cut to the frame with the biggest change near it (scene detection can be a frame off)
    fcuts = []
    for c in cuts:
        f = int(round(c * OUT_FPS))
        lo, hi = max(1, f - 2), min(nfr - 1, f + 2)
        if hi > lo:
            f = lo + int(np.argmax(diff[lo:hi + 1]))
        if not fcuts or f - fcuts[-1] >= 3:
            fcuts.append(f)
    total_f = int(round(dur * OUT_FPS))
    bounds = [0] + [f for f in fcuts if 0 < f < total_f - 3] + [total_f]
    # merge slivers (< 0.2 s) created by flashes or detector jitter into the previous shot
    merged = [bounds[0]]
    for f in bounds[1:]:
        if f - merged[-1] < 6 and f != bounds[-1]:
            continue
        if f == bounds[-1] and f - merged[-1] < 6 and len(merged) > 1:
            merged[-1] = f
            continue
        merged.append(f)
    bounds = merged
    # flash frames: a 1-4 frame burst of white around a cut becomes a "flash" transition
    dissolve_at = {k for k, f in enumerate(bounds[1:-1], 1) if any(abs(f / OUT_FPS - d) < 0.07 for d in dissolves)}
    flash_at = set()
    med = np.median(mean) if nfr else 128
    for k, f in enumerate(bounds[1:-1], 1):
        win = mean[max(0, f - 3): min(nfr, f + 4)]
        if len(win) and win.max() > max(200, med * 1.45):
            flash_at.add(k)
    shots = []
    fdir = rdir / "frames"
    fdir.mkdir(exist_ok=True)
    for k, (a, b) in enumerate(zip(bounds[:-1], bounds[1:])):
        t0, t1 = a / OUT_FPS, b / OUT_FPS
        mid = (t0 + t1) / 2
        motion = float(np.mean(diff[a + 1:b])) if b - a > 2 and b <= nfr else 0.0
        fr = _grab(p, mid, fdir / f"R{k + 1:02d}.jpg")
        txt = _grab(p, t0 + 0.75 * (t1 - t0), fdir / f"R{k + 1:02d}_in.jpg")  # animated text is in by now
        shots.append({"id": f"R{k + 1:02d}", "t0": round(t0, 4), "t1": round(t1, 4), "dur": round(t1 - t0, 4),
                      "f0": a, "f1": b, "motion": round(motion, 2), "frame": str(fr) if fr else None,
                      "frame_in": str(txt) if txt else None, "flash_in": k in flash_at,
                      "dissolve_in": k in dissolve_at})
    has_audio = any(s.get("codec_type") == "audio" for s in info.get("streams", []))
    audio = None
    if has_audio:
        audio = rdir / "sound.wav"
        subprocess.run(ffmpeg_base() + ["-i", str(p), "-vn", "-ac", "2", "-ar", "44100", str(audio)],
                       capture_output=True)
        if not audio.exists():
            audio = None
    res = {"version": 7, "source": ref, "file": str(p), "duration": round(total_f / OUT_FPS, 4),
           "shots": shots, "audio": str(audio) if audio else None, "dir": str(rdir)}
    write_json(rdir / "reference.json", res)
    log(f"reference: {len(shots)} shots, median {np.median([s['dur'] for s in shots]):.2f}s"
        + (f", {len(flash_at)} flash cut(s)" if flash_at else ""))
    return res


def _sheet(paths: list[tuple[str, str]], out: Path, cols: int = 6, tile=(240, 427)) -> Path:
    from PIL import Image, ImageDraw
    from .text import load_font
    rows = math.ceil(len(paths) / cols)
    sheet = Image.new("RGB", (cols * (tile[0] + 6) + 6, rows * (tile[1] + 6) + 6), (30, 30, 30))
    d = ImageDraw.Draw(sheet)
    font = load_font(26, "bold")
    for i, (label, p) in enumerate(paths):
        x, y = 6 + (i % cols) * (tile[0] + 6), 6 + (i // cols) * (tile[1] + 6)
        try:
            with Image.open(p) as im:
                im = im.convert("RGB")
                im.thumbnail(tile)
                sheet.paste(im, (x + (tile[0] - im.width) // 2, y + (tile[1] - im.height) // 2))
        except Exception:
            pass
        d.rectangle([x, y, x + 64, y + 34], fill=(255, 214, 0))
        d.text((x + 6, y + 3), label, font=font, fill=(0, 0, 0))
    sheet.save(out, "JPEG", quality=86)
    return out


def describe_reference(ref: dict, backend) -> dict:
    """AI: what each reference shot shows + its on-screen text. Cached next to the reference."""
    from .ai import extract_json
    rdir = Path(ref["dir"])
    cache = read_json(rdir / "slots.json")
    if cache and len(cache.get("shots", [])) == len(ref["shots"]):
        return cache
    if backend is None:
        out = {"shots": [{"id": s["id"], "type": "other", "content": "", "camera": "static",
                          "energy": "intense" if s["dur"] < 0.8 else ("calm" if s["dur"] > 2.2 else "medium"),
                          "text": "", "text_pos": "center", "text_role": "caption"} for s in ref["shots"]],
               "source": "none"}
        return out
    got = {}
    for b in range(0, len(ref["shots"]), 18):
        batch = ref["shots"][b:b + 18]
        sheet = _sheet([(s["id"], s.get("frame_in") or s["frame"]) for s in batch if s.get("frame")],
                       rdir / f"slots_{b // 18 + 1}.jpg")
        timing = ", ".join(f"{s['id']} {s['t0']:.2f}-{s['t1']:.2f}s" for s in batch)
        log(f"AI: reading reference shots {batch[0]['id']}-{batch[-1]['id']} ({backend.name})")
        try:
            data = extract_json(backend.ask(SLOT_PROMPT.format(timing=timing, types=", ".join(TYPES)), [sheet],
                                            max_tokens=3000))
            rows = data.get("shots", data) if isinstance(data, dict) else data
            for r in rows or []:
                if isinstance(r, dict) and r.get("id"):
                    got[str(r["id"]).upper()] = r
        except Exception as e:
            log(f"  could not read reference shots ({e})")
    shots = []
    for s in ref["shots"]:
        r = got.get(s["id"], {})
        shots.append({"id": s["id"], "type": r.get("type") if r.get("type") in TYPES else "other",
                      "content": str(r.get("content", ""))[:80], "camera": str(r.get("camera", "static")),
                      "energy": r.get("energy") if r.get("energy") in ("calm", "medium", "intense") else "medium",
                      "text": str(r.get("text") or "").strip(), "text_pos": r.get("text_pos", "center"),
                      "text_role": r.get("text_role", "caption")})
    out = {"shots": shots, "source": backend.name}
    write_json(rdir / "slots.json", out)
    return out


# ================================================================ matching
_TYPE_TAGS = {"wide_landscape": ["landscape", "mountain", "valley", "vista", "panorama", "peak", "wide"],
              "aerial": ["aerial", "drone"], "close_detail": ["detail", "close", "macro", "flower", "texture"],
              "person": ["person", "people", "hiker", "portrait", "selfie"],
              "walking_pov": ["pov", "walking", "trail", "hike", "path"],
              "water": ["water", "lake", "ocean", "sea", "beach", "waterfall", "river", "coast"],
              "city": ["city", "street", "building", "architecture", "town", "castle"],
              "road_vehicle": ["road", "car", "drive", "train", "boat", "vehicle"],
              "sky": ["sky", "sunset", "sunrise", "clouds", "golden"], "night": ["night", "stars", "lights"],
              "food": ["food", "cafe", "drink"], "wildlife": ["animal", "wildlife", "bird", "tiger"],
              "interior": ["interior", "room", "hotel"], "other": []}


def _fits(shot: dict, dur: float) -> bool:
    return shot["kind"] == "photo" or (shot["t1"] - shot["t0"]) >= dur * 0.6


def heuristic_match(slots: list[dict], ref_shots: list[dict], shots: list[dict]) -> dict[str, list[str]]:
    used: dict[str, int] = {}
    out = {}
    for sl, rs in zip(slots, ref_shots):
        want = _TYPE_TAGS.get(sl["type"], [])
        moving_slot = rs["motion"] > 6 or sl["camera"] in ("pan", "handheld", "drone", "push")

        def score(s):
            a = s.get("ai", {})
            text = " ".join(a.get("tags", [])) + " " + a.get("note", "")
            v = float(a.get("score", 5))
            v += 1.5 * sum(1 for w in want if w in text.lower())
            v += 0.8 if (s["kind"] == "video") == moving_slot else 0
            v -= 3.0 * used.get(s["id"], 0)
            v -= 4.0 if not _fits(s, rs["dur"]) else 0
            return v
        ranked = sorted(shots, key=score, reverse=True)[:3]
        out[sl["id"]] = [s["id"] for s in ranked]
        if ranked:
            used[ranked[0]["id"]] = used.get(ranked[0]["id"], 0) + 1
    return out


def ai_match(slots, ref_shots, shots, places, backend, rdir: Path) -> tuple[dict, dict]:
    from .ai import extract_json
    by_id = {s["id"]: s for s in shots}
    sl_txt = "\n".join(f"{sl['id']}: {rs['dur']:.2f}s, {sl['type']}, \"{sl['content']}\", camera {sl['camera']}, "
                       f"{sl['energy']}" + (f", text \"{sl['text']}\" ({sl['text_role']})" if sl["text"] else "")
                       for sl, rs in zip(slots, ref_shots))
    pool = sorted(shots, key=lambda s: -float(s.get("ai", {}).get("score", 5)))[:60]
    sh_txt = "\n".join(
        f"{s['id']}: {s['kind']}, {('%.1fs' % (s['t1'] - s['t0'])) if s['kind'] == 'video' else 'any length'}, "
        f"{s.get('ai', {}).get('score', 5)}, {','.join(s.get('ai', {}).get('tags', []))}, "
        f"\"{s.get('ai', {}).get('note', '')}\"" + (f", {places.get(s['id'])}" if places.get(s["id"]) else "")
        for s in pool)
    plist = list(dict.fromkeys(v for v in places.values() if v))
    hint = f"; the user's places: {', '.join(plist[:8])}" if plist else ""
    key = short_hash(sl_txt + sh_txt + hint, 12)
    cache = read_json(rdir / f"match_{key}.json")
    if cache:
        return cache["slots"], cache["texts"]
    log(f"AI: matching {len(slots)} slots to your shots ({backend.name})")
    data = extract_json(backend.ask(MATCH_PROMPT.format(slots=sl_txt, shots=sh_txt, places_hint=hint), None,
                                    max_tokens=4000))
    m = {}
    for r in data.get("slots", []):
        ids = [str(i).upper() for i in (r.get("shots") or []) if str(i).upper() in by_id]
        if ids:
            m[str(r.get("id", "")).upper()] = ids[:3]
    texts = {}
    for r in data.get("texts", []):
        new = r.get("new")
        new = [new] if isinstance(new, str) else [str(x) for x in (new or []) if str(x).strip()]
        if r.get("ref") and new:
            texts[str(r["ref"]).strip()] = new[:3]
    write_json(rdir / f"match_{key}.json", {"slots": m, "texts": texts})
    return m, texts


# ================================================================ plan
def _assign(slots, ref_shots, match, shots_by_id, variant: int) -> list[str]:
    """One shot per slot: the variant-th choice where possible, no repeats while there is choice."""
    used = set()
    out = []
    for sl, rs in zip(slots, ref_shots):
        cands = list(match.get(sl["id"], []))
        if not cands:
            cands = [s for s in shots_by_id]
        order = cands[variant:] + cands[:variant] if variant < len(cands) else cands
        pick = next((c for c in order if c not in used and _fits(shots_by_id[c], rs["dur"])), None) or \
            next((c for c in order if c not in used), None) or order[0]
        used.add(pick)
        out.append(pick)
    return out


def build_clone_plan(ref: dict, slots: list[dict], match: dict, texts: dict, shots: list[dict], style: dict,
                     variant: int = 0, keep_text: bool = False) -> dict:
    from .music import analyze_music
    from .planner import _entry_for, _snap, choose_transitions  # noqa: F401
    by_id = {s["id"]: s for s in shots}
    rshots = ref["shots"]
    picks = _assign(slots, rshots, match, by_id, variant)
    total = ref["duration"]
    beats, drops, tempo = [], [], 0.0
    if ref.get("audio"):
        mus = analyze_music(Path(ref["audio"]), Path(ref["dir"]))
        beats = [round(b, 4) for b in mus["beats"] if b <= total + 0.01]
        tempo = mus["tempo"]
        en = mus.get("energy") or [0.5] * len(mus["beats"])
        for j in range(4, len(beats) - 3):
            if np.mean(en[j:j + 4]) - np.mean(en[max(0, j - 4):j]) > 0.22 and 0.3 < beats[j] < total - 0.5:
                if not drops or beats[j] - drops[-1] > 2.0:
                    drops.append(beats[j])
    segs = []
    kb_dir = 0
    for k, (rs, sl, sid) in enumerate(zip(rshots, slots, picks)):
        level = sl.get("energy", "medium")
        seg = {"out_start": round(rs["f0"] / OUT_FPS, 4), "dur": round((rs["f1"] - rs["f0"]) / OUT_FPS, 4),
               "level": level}
        e, kb_dir = _entry_for(by_id[sid], seg, style, kb_dir)
        e.update({"idx": k, "clone_of": rs["id"], "trans_out": None, "trans_dur": 0.0, "trans_params": {},
                  "drop": any(abs(seg["out_start"] - d) < 0.12 for d in drops)})
        segs.append(e)
    for k in range(len(segs) - 1):  # the reference's flash cuts and dissolves
        if rshots[k + 1].get("flash_in"):
            segs[k]["trans_out"] = "flash"
        elif rshots[k + 1].get("dissolve_in"):
            segs[k]["trans_out"], segs[k]["trans_dur"] = "dissolve", 0.33
    # on-screen text: consecutive shots showing the same text form one overlay
    overlays = []
    k = 0
    role_map = {"hook": "hook", "location": "location", "cta": "cta", "label": "label", "caption": "label"}
    while k < len(slots):
        t = slots[k].get("text", "")
        if not t:
            k += 1
            continue
        j = k
        while j + 1 < len(slots) and slots[j + 1].get("text", "") == t:
            j += 1
        new = texts.get(t)
        txt = (new[min(variant, len(new) - 1)] if new else (t if keep_text else None))
        if txt:
            role = role_map.get(slots[k].get("text_role", "caption"), "label")
            if k == 0 and role == "label":
                role = "hook"
            st = rshots[k]["t0"] + (0.1 if k == 0 else 0.05)
            overlays.append({"type": role, "text": txt, "start": round(st, 3),
                             "duration": round(rshots[j]["t1"] - st - 0.08, 3), "clone_of": t})
        k = j + 1
    return {
        "version": 1, "style": style["name"], "duration": round(total, 4), "tempo": round(tempo, 1),
        "music": {"path": ref.get("audio"), "start": 0.0, "fade_out": 0.3},
        "transition_duration": 0.3, "color": style["color"], "text": style["text"], "segments": segs,
        "overlays": overlays, "beats": beats, "drops": drops, "motion": style.get("motion", {}),
        "loop": False, "clone": {"source": ref["source"], "variant": variant + 1},
    }


def compare_sheet(ref: dict, plan: dict, by_id: dict, out: Path) -> Path:
    """Reference shot | your shot (graded), slot by slot."""
    from PIL import Image, ImageDraw
    from .text import load_font, _vertical_tile
    tw, th = 160, 284
    segs = plan["segments"]
    cols = min(8, len(segs))
    rows = math.ceil(len(segs) / cols)
    img = Image.new("RGB", (cols * (2 * tw + 18) + 10, rows * (th + 46) + 56), (22, 22, 22))
    d = ImageDraw.Draw(img)
    f = load_font(22, "bold")
    fs = load_font(15, "regular")
    d.text((12, 14), f"reference  vs  your clone (variant {plan.get('clone', {}).get('variant', 1)})", font=f,
           fill=(255, 214, 0))
    rmap = {s["id"]: s for s in ref["shots"]}
    for i, e in enumerate(segs):
        x = 10 + (i % cols) * (2 * tw + 18)
        y = 50 + (i // cols) * (th + 46)
        rs = rmap.get(e.get("clone_of"), {})
        try:
            with Image.open(rs.get("frame")) as im:
                im = im.convert("RGB")
                im.thumbnail((tw, th))
                img.paste(im, (x + (tw - im.width) // 2, y + (th - im.height) // 2))
        except Exception:
            pass
        tile = _vertical_tile(by_id.get(e["shot_id"], {}).get("thumb", ""), (tw, th), float(e.get("subject_x", 0.5)),
                              e.get("layout", ""))
        if e.get("lut") and Path(e["lut"]).exists():
            from .grade import apply_cube
            tile = Image.fromarray(apply_cube(np.asarray(tile.convert("RGB")), Path(e["lut"])))
        img.paste(tile, (x + tw + 4, y))
        d.text((x, y + th + 4), f"{e.get('clone_of')} {e['dur']:.2f}s -> {e['shot_id']}", font=fs, fill=(220, 220, 220))
    img.save(out, "JPEG", quality=86)
    return out
