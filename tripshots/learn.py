"""`tripshots learn`: reverse-engineer reference reels into a reusable style YAML.

Measures cut timing (and how tightly cuts follow the beat), shot length in
beats, colour grade versus neutral, and asks the AI to describe text, transitions
and mood from sampled frames. Writes ~/.tripshots/styles/<name>.yaml.
"""
from __future__ import annotations

import re
from pathlib import Path

import cv2
import numpy as np
import yaml
from PIL import Image

from . import ai as ai_mod
from .config import DEFAULT_STYLE, HOME, USER_STYLES
from .fetch import fetch_video
from .music import analyze_music
from .util import ReelError, deep_merge, ffmpeg_base, ffprobe, log, run, write_json


def _scenes(path: Path) -> list[float]:
    from scenedetect import AdaptiveDetector, detect
    scenes = detect(str(path), AdaptiveDetector(adaptive_threshold=2.6, min_scene_len=6))
    return [s[0].get_seconds() for s in scenes][1:]  # cut times (exclude 0)


def _grab(path: Path, t: float, out: Path) -> Path | None:
    proc = run(ffmpeg_base() + ["-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1", "-vf", "scale=360:-2",
                                "-q:v", "3", str(out)], check=False)
    return out if proc.returncode == 0 and out.exists() else None


def _grade(frames: list[Path]) -> dict:
    sats, vals, warm, contrast = [], [], [], []
    for f in frames:
        img = cv2.imread(str(f))
        if img is None:
            continue
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        sats.append(hsv[..., 1].mean() / 255)
        vals.append(hsv[..., 2].mean() / 255)
        b, g, r = (img[..., i].astype(float).mean() for i in range(3))
        warm.append((r - b) / 255)
        contrast.append(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).std() / 255)
    if not sats:
        return {}
    return {"saturation": float(np.mean(sats)), "brightness": float(np.mean(vals)),
            "warmth": float(np.mean(warm)), "contrast": float(np.mean(contrast))}


def measure(path: Path, work: Path) -> dict:
    info = ffprobe(path)
    dur = float(info.get("format", {}).get("duration", 0))
    cuts = _scenes(path)
    bounds = [0.0] + cuts + [dur]
    lens = np.diff(bounds)
    res = {"file": str(path), "duration": round(dur, 2), "cuts": len(cuts),
           "shot_len_median": round(float(np.median(lens)), 2) if len(lens) else None,
           "shot_len_p25": round(float(np.percentile(lens, 25)), 2) if len(lens) else None,
           "shot_len_p75": round(float(np.percentile(lens, 75)), 2) if len(lens) else None,
           "first_shot": round(float(lens[0]), 2) if len(lens) else None}
    has_audio = any(s.get("codec_type") == "audio" for s in info.get("streams", []))
    if has_audio and cuts:
        wav = work / f"{path.stem}.wav"
        run(ffmpeg_base() + ["-i", str(path), "-vn", "-ac", "1", "-ar", "22050", str(wav)], check=False)
        if wav.exists():
            m = analyze_music(wav, work)
            beats = np.array(m["beats"])
            bl = 60.0 / m["tempo"] if m["tempo"] else 0.5
            near = [float(np.min(np.abs(beats - c))) for c in cuts] if len(beats) else []
            res.update({"tempo": m["tempo"],
                        "cuts_on_beat_pct": round(100 * float(np.mean([d < 0.09 for d in near])), 0) if near else None,
                        "beats_per_shot_median": round(float(np.median(lens)) / bl, 2)})
    # sample frames: middle of each shot (max 16) for grade + AI look
    mids = [(a + b) / 2 for a, b in zip(bounds[:-1], bounds[1:])]
    if len(mids) > 16:
        mids = [mids[int(i)] for i in np.linspace(0, len(mids) - 1, 16)]
    frames = []
    fd = work / f"{path.stem}_frames"
    fd.mkdir(parents=True, exist_ok=True)
    for i, t in enumerate(mids):
        f = _grab(path, t, fd / f"f{i:02d}.jpg")
        if f:
            frames.append(f)
    res["grade"] = _grade(frames)
    res["frames"] = [str(f) for f in frames]
    # extra frames near the start to read hook text
    res["early_frames"] = [str(f) for f in (_grab(path, t, fd / f"early{t:.1f}.jpg") for t in (0.3, 1.2, 2.2)) if f]
    return res


def sheet(frames: list[str], out: Path, cols: int = 6) -> Path:
    tiles = [Image.open(f).convert("RGB") for f in frames]
    tw = 240
    th = int(tw * 16 / 9)
    rows = (len(tiles) + cols - 1) // cols
    img = Image.new("RGB", (cols * tw, rows * th), (0, 0, 0))
    for i, t in enumerate(tiles):
        t.thumbnail((tw, th))
        img.paste(t, ((i % cols) * tw, (i // cols) * th))
    img.save(out, "JPEG", quality=86)
    return out


STYLE_PROMPT = """You are reverse-engineering the editing style of reference Instagram Reels so an automated editor can copy it for SILENT scenic travel footage set to music.

Image 1+: frames sampled from the middle of each shot of the reference reel(s), in order. The last image(s) show the first ~2 seconds (look for on-screen hook text).
Measurements:
{measures}

Write a style YAML for the editor. Use ONLY these keys (omit anything you are unsure of):
name: {name}
description: one sentence describing the vibe
duration: {{target: <sec>, min: <sec>, max: <sec>}}
cuts:
  beats_per_cut: {{calm: <1|2|4|8>, medium: <1|2|4>, intense: <1|2|4>}}
  hook_beats: <1-4>
  min_shot_sec: <float>
  max_shot_sec: <float>
shots:
  ordering: energy | chronological | score
  slowmo: true|false
layout:
  landscape: auto | crop | pan | blur_fill
  photo_motion: kenburns | static
  photo_zoom: <1.0-1.25>
transitions:
  palette: {{calm: [..], medium: [..], intense: [..]}}   # pick from: whip, zoom_in, zoom_out, spin, flash, glitch, blur, dissolve, dip
  density: <0.0-1.0>   # share of cuts that use a transition (0 = all hard cuts on the beat)
  speed: <0.6-1.6>     # <1 = snappier transitions, >1 = slower
  at: sections|none    # sections = always transition when the energy changes / on the drop
panels:               # split screens / grids (several clips on screen at once)
  use: <0-1>           # 0 = never seen in the references; ~0.4 = a moment or two; ~0.9 = a lot
  kinds: [split2|split3|grid4|columns3]
  mode: reveal|cycle|mixed   # reveal = panels appear one per beat; cycle = they keep cutting to new clips
velocity: {{use: <0-1>}}   # speed ramps: fast motion slamming into slow motion on the hit
loop: true|false       # the ending flows back into the first shot
motion:
  pulse: <0-0.15>      # bulge/"pop" distortion on bass hits
  beat_punch: <0-0.1>  # zoom bump on beats (0.04-0.08 typical for energetic edits)
  punch_on: [medium, intense]
  shake_on_drop: true|false
  video_push: <0-0.1>  # slow zoom on static clips
color: {{saturation: <0.7-1.4>, contrast: <0.85-1.25>, brightness: <-0.08-0.08>, gamma: <0.85-1.15>, warmth: <-0.15-0.15>, vignette: true|false, sharpen: <0-0.8>}}
text:
  preset: bold|editorial|minimal|handwritten|typewriter   # bold = heavy condensed caps popping in on beats; editorial = elegant serif/italic sliding up; minimal = small tracked sans; handwritten = marker/script; typewriter = monospace typed
  hook: {{mode: off|ai, position: auto|upper|center|lower, duration: <sec>}}
  location: {{mode: off|first|each, coords: true|false}}   # coords = small GPS line under the place name
  cta: {{mode: off|ai}}   # closing "save this" style line
  labels: {{mode: off|ai}}  # a short label on each shot ("Golden hour", "Highway 1")
caption: {{tone: "<few words>", hashtags: <5-20>}}

Guidance: beats_per_cut should reproduce the measured beats-per-shot (round to 1/2/4/8). Look closely at the frames for transition evidence: motion-blur smears (whip), radial blur or extreme zoom (zoom_in), rotated frames (spin), white frames (flash), RGB fringing (glitch), double exposures (dissolve). Set density to roughly the share of cuts that are not plain hard cuts. Colour values are adjustments applied on top of normal phone footage to approximate the reference grade (measured grade: saturation ~0.35 and warmth ~0.0 is neutral). Reply with ONLY the YAML."""


def learn(refs: list[str], name: str, backend_name: str | None, cookies_browser: str | None,
          cookies_file: str | None = None) -> Path:
    work = HOME / "learn" / name
    work.mkdir(parents=True, exist_ok=True)
    measures = []
    for r in refs:
        p = Path(r).expanduser()
        if not p.exists():
            if not re.match(r"https?://", r):
                raise ReelError(f"not a file or URL: {r}")
            log(f"downloading {r}")
            p = fetch_video(r, work / "downloads", cookies_browser, cookies_file)
        log(f"measuring {p.name}")
        measures.append(measure(p, work))
    write_json(work / "measurements.json", measures)
    # numeric baseline from measurements
    bps = [m["beats_per_shot_median"] for m in measures if m.get("beats_per_shot_median")]
    lens = [m["shot_len_median"] for m in measures if m.get("shot_len_median")]
    durs = [m["duration"] for m in measures]
    base = {"name": name, "description": f"Learned from {len(refs)} reference reel(s)."}
    if durs:
        d = float(np.median(durs))
        base["duration"] = {"target": round(d), "min": max(6, round(d * 0.7)), "max": round(d * 1.4) + 1}
    if bps:
        b = float(np.median(bps))
        q = min((1, 2, 4, 8), key=lambda x: abs(x - b))
        base["cuts"] = {"beats_per_cut": {"calm": min(8, q * 2), "medium": q, "intense": max(1, q // 2 if q > 1 else 1)}}
    if lens:
        l = float(np.median(lens))
        base.setdefault("cuts", {}).update({"min_shot_sec": round(max(0.3, l * 0.45), 2),
                                            "max_shot_sec": round(min(6.0, l * 2.2), 2)})
    style = base
    backend = ai_mod.get_backend(backend_name)
    if backend:
        frames = [f for m in measures for f in m["frames"]][:24]
        early = [f for m in measures for f in m["early_frames"]][:6]
        imgs = [sheet(frames, work / "shots_sheet.jpg")]
        if early:
            imgs.append(sheet(early, work / "early_sheet.jpg", cols=3))
        slim = [{k: v for k, v in m.items() if k not in ("frames", "early_frames", "file")} for m in measures]
        prompt = STYLE_PROMPT.format(measures=yaml.safe_dump(slim, sort_keys=False), name=name)
        try:
            reply = backend.ask(prompt, imgs, max_tokens=1500)
            m = re.search(r"```(?:ya?ml)?\s*(.*?)```", reply, re.S)
            ai_style = yaml.safe_load(m.group(1) if m else reply) or {}
            if isinstance(ai_style, dict):
                style = deep_merge(base, ai_style)
                # measurements win for timing
                if bps:
                    style["cuts"]["beats_per_cut"]["medium"] = base["cuts"]["beats_per_cut"]["medium"]
        except Exception as e:
            log(f"AI style description failed ({e}); saving measured timing only")
    # colour: the references' grade becomes a look with the same name
    try:
        from . import grade
        imgs = [cv2.cvtColor(im, cv2.COLOR_BGR2RGB) for im in (cv2.imread(f) for m in measures for f in m["frames"])
                if im is not None]
        if imgs:
            lk = grade.look_from_images(imgs, name, f"Colour of the reels the '{name}' style was learned from.")
            lk["refs"] = refs
            grade.save_look(lk, name)
            style["grade"] = {"look": name, "strength": 0.75, "ai": True}
            log(f"look saved: {name} (colour grade of the references)")
    except Exception as e:
        log(f"could not measure the references' colour ({e})")
    style["name"] = name
    style["learned_from"] = refs
    # validate keys against the schema
    clean = {k: v for k, v in style.items() if k in DEFAULT_STYLE or k == "learned_from"}
    USER_STYLES.mkdir(parents=True, exist_ok=True)
    out = USER_STYLES / f"{name}.yaml"
    out.write_text(yaml.safe_dump(clean, sort_keys=False, allow_unicode=True))
    log(f"style saved: {out}")
    for m in measures:
        log(f"  {Path(m['file']).name}: {m['cuts']} cuts, median shot {m['shot_len_median']}s"
            + (f", {m.get('beats_per_shot_median')} beats/shot, {m.get('cuts_on_beat_pct')}% cuts on beat"
               if m.get("tempo") else ""))
    return out
