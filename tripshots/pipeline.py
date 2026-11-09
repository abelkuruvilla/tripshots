"""High-level orchestration for `tripshots make`."""
from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path

from . import ai as ai_mod
from .config import cache_dir_for, default_out_dir, load_style
from .geo import place_name
from .media import ingest
from .music import analyze_music
from .planner import add_location_overlays, build_plan
from .render import export_cover, render
from .shots import analyze, heuristic_scores
from .text import storyboard
from .fetch import audio_meta, fetch_audio, is_url
from .util import ReelError, ffmpeg_base, log, read_json, run, write_json


def _exports(plan_path: Path) -> dict:
    """EDL + storyboard.md next to every plan (OTIO on request: `tripshots export`)."""
    try:
        from .export import export
        return export(plan_path, edl=True, otio=False, md=True, quiet=True)
    except Exception as e:  # an export must never stop a reel
        log(f"editor export skipped: {e}")
        return {}


def prepare_shots(inputs: list[Path], backend_name: str | None, work: Path | None = None,
                  source_opts: dict | None = None, rescore: bool = False, watch_mode: str | None = None):
    work = work or cache_dir_for(inputs)
    media = ingest(inputs, work, source_opts)
    shots = analyze(media, work)
    if not shots:
        raise ReelError("No usable shots were found.")
    heur = heuristic_scores(shots)
    backend = ai_mod.get_backend(backend_name)
    scores = {}
    if backend:
        try:
            scores = ai_mod.score_shots(shots, backend, work, rescore=rescore)
        except Exception as e:
            log(f"AI scoring failed ({e}); falling back to heuristics")
    missing = 0
    for s in shots:
        a = scores.get(s["id"])
        if a is None:
            missing += 1
            a = heur[s["id"]]
        else:
            # blend: AI taste + technical guardrails (blurry/shaky shots get pulled down)
            h = heur[s["id"]]["score"]
            if h < 4:
                a = {**a, "score": round(min(a["score"], (a["score"] + h) / 2), 1)}
        s["ai"] = a
    if backend and missing:
        log(f"{missing} shots used heuristic scores")
    from . import watch as watch_mod
    mode = watch_mode or (source_opts or {}).get("watch") or os.environ.get("TRIPSHOTS_WATCH", "auto")
    logs = {}
    if mode != "off" and (mode == "gemini" or watch_mod.api_key()):
        logs = watch_mod.watch_media(media, work)
    changed = watch_mod.apply(shots, logs)
    if changed:
        log(f"watch: {changed} shots scored with what Gemini saw (best instant, shake, tilt, exposure)")
    write_json(work / "shots_scored.json", shots)
    return shots, backend, work


def resolve_music(music: str | Path | None, cookies: dict | None = None) -> tuple[Path | None, dict]:
    """A local audio file, or a reel/video URL whose soundtrack is downloaded."""
    if not music:
        return None, {}
    if is_url(str(music)):
        path = fetch_audio(str(music), **(cookies or {}))
        return path, {**audio_meta(path), "from_url": True}
    p = Path(music).expanduser()
    if not p.exists():
        raise ReelError(f"music file not found: {p}")
    return p, audio_meta(p)


def make(inputs: list[Path], music: str | Path | None, style_name: str | None, out: Path | None,
         duration: float | None, backend_name: str | None, hook: str | None, location: str | None,
         no_location: bool, dry_run: bool, workers: int = 2, source_opts: dict | None = None,
         cookies: dict | None = None, music_start: float | None = None, upload_copy: bool | None = None,
         min_score: float | None = None, allow_similar: bool = False, rescore: bool = False,
         text_preset: str | None = None, behind: str | None = None, extras: dict | None = None,
         look: str | None = None, grade_strength: float | None = None, route_map: str | None = None,
         sound: dict | None = None) -> dict:
    style = load_style(style_name)
    if look:
        style["grade"]["look"] = look
    lk = str(style["grade"].get("look") or "auto")
    if lk not in ("auto", "none", "off"):
        from .grade import get_look
        try:
            get_look(lk)
        except KeyError as e:
            raise ReelError(str(e).strip("'\""))
    if route_map:
        style.setdefault("route_map", {})["mode"] = route_map
    style.setdefault("sound", {}).update({k: v for k, v in (sound or {}).items() if v is not None})
    if grade_strength is not None:
        style["grade"]["strength"] = float(grade_strength)
    ex = extras or {}
    if ex.get("split"):
        style.setdefault("panels", {})["use"] = {"lots": 0.9, "some": 0.4, "off": 0.0}[ex["split"]]
        if ex["split"] != "off":
            style["panels"]["max"] = max(int(style["panels"].get("max", 2)), 3 if ex["split"] == "lots" else 1)
    sp = style.setdefault("speed", {})
    if ex.get("ramps"):
        r = str(ex["ramps"]).strip().lower()
        vel = style.setdefault("velocity", {})
        if r == "off":
            vel["use"] = 0.0
        else:
            if r != "on":
                from .retime import KINDS
                kinds = [k.strip() for k in r.split(",") if k.strip()]
                bad = [k for k in kinds if k not in KINDS]
                if bad:
                    raise ReelError(f"unknown speed ramp {', '.join(bad)}: use on, off or {', '.join(KINDS)}")
                sp["ramps"] = kinds
            vel["use"] = max(0.35, float(vel.get("use", 0) or 0))
    if ex.get("speed_up"):
        sp["fast"] = max(0.3, float(sp.get("fast", 0) or 0)) if ex["speed_up"] == "on" else 0.0
    if ex.get("drop_speed"):
        sp["drop"] = ex["drop_speed"]
    if ex.get("smooth"):
        sp["smooth"] = ex["smooth"]
    if ex.get("labels"):
        style["text"].setdefault("labels", {})["mode"] = ex["labels"]
    stc = style.setdefault("story", {})
    for k in ("format", "arc", "captions", "critic", "parallax"):
        if ex.get(k):
            stc[k] = ex[k]
    if ex.get("variant"):
        style["shots"]["variant"] = int(ex["variant"])
    if ex.get("avoid_hooks"):
        style["_avoid_hooks"] = list(ex["avoid_hooks"])
    if ex.get("loop") is not None:
        style["loop"] = bool(ex["loop"])
    if text_preset:
        style["text"]["preset"] = text_preset
    if ex.get("text_motion"):
        style["text"]["motion"] = ex["text_motion"]
    if behind:
        style["text"]["location"]["behind"] = behind
    if min_score is not None:
        style["shots"]["min_score"] = float(min_score) + 2  # planner allows min_score - 2 when footage is thin
    if allow_similar:
        style["shots"]["allow_similar"] = True
    if no_location:
        style["text"]["location"]["mode"] = "off"
    music, mmeta = resolve_music(music, cookies)  # download first: fails fast on a bad link
    if music_start is not None:
        style["music"]["window"] = float(music_start)
    elif mmeta.get("from_url"):
        # a reel's sound starts where Instagram starts it; cutting from 0:00 keeps the edit
        # in sync when you attach the same sound in the app
        style["music"]["window"] = 0.0
    if upload_copy is None:
        upload_copy = bool(mmeta.get("from_url"))
    shots, backend, work = prepare_shots(inputs, backend_name, source_opts=source_opts, rescore=rescore)
    by_id = {s["id"]: s for s in shots}
    mus = analyze_music(music, work) if music else None
    if not music:
        log("no --music given: rendering a silent reel timed to 100 BPM (add a trending sound in Instagram)")
    st = style.setdefault("story", {})
    arc = str(st.get("arc", "on")).lower() not in ("off", "false", "0", "none")
    words = None
    places_all: dict = {}
    if arc:
        if music and str(st.get("words", "auto")) != "off":
            from . import lyrics
            words = lyrics.words(music, mus.get("duration") if mus else None)
            style["_words"] = words
        if style["text"]["location"].get("mode") != "off" or str(st.get("format")) in ("auto", "list"):
            seen: dict = {}
            for s in sorted(shots, key=lambda s: -float(s.get("ai", {}).get("score", 5)))[:60]:
                if s.get("gps"):
                    k = (round(s["gps"][0], 2), round(s["gps"][1], 2))
                    if k not in seen:
                        seen[k] = place_name(*s["gps"])
                    places_all[s["id"]] = seen[k]
        from . import formats, results as results_mod
        fmt = formats.choose(str(st.get("format") or "auto"), shots, places_all, words, results_mod.preferences())
        if fmt == "list" and len({formats.short_place(v) for v in places_all.values() if v}) < 3:
            fmt = "montage"
        if int(ex.get("variant") or 0) == 1 and str(st.get("format") or "auto") == "auto":
            # the second variant tests a different idea, not just a different first shot
            fmt = {"montage": "reveal", "list": "montage", "pov": "montage", "series": "reveal",
                   "reveal": "montage"}[fmt]
        st["format"] = fmt
        style["_places"] = places_all
        log(f"format: {fmt}")
    plan = build_plan(shots, mus, style, duration, str(music.resolve()) if music else None)
    plan["photo_zoom"] = style["layout"].get("photo_zoom", 1.12)
    words_rel = None
    if arc and words and words.get("lines"):
        from . import lyrics
        words_rel = lyrics.window(words, float(plan["music"]["start"] or 0), plan["duration"] + 0.5)
        plan["words"] = {k: words_rel.get(k) for k in ("kind", "language", "punch_t", "source")}
    if mmeta:
        plan["music"]["label"] = mmeta.get("label")
        plan["music"]["source_url"] = mmeta.get("url")

    # location labels from GPS
    places = {}
    if style["text"]["location"].get("mode") != "off" and not location:
        for seg in plan["segments"]:
            s = by_id[seg["shot_id"]]
            if s.get("gps"):
                places[s["id"]] = place_name(*s["gps"])
    hook_cfg = style["text"]["hook"]
    if arc and st.get("hook_text", "on") == "on" and hook_cfg.get("mode") == "off":
        hook_cfg = {**hook_cfg, "mode": "ai"}
        style["text"]["hook"] = hook_cfg
    copy = {}
    if backend and arc:
        from . import formats
        day, n_days = formats.trip_day([by_id[sg["shot_id"]] for sg in plan["segments"] if sg.get("shot_id") in by_id],
                                       shots)
        fmt = st.get("format", "montage")
        if fmt == "series" and not day:
            fmt = st["format"] = "montage"
        plist = [formats.short_place(places_all.get(sg["shot_id"])) for sg in plan["segments"]]
        plist = [p for p in dict.fromkeys(plist) if p] + ([location] if location else [])
        copy = ai_mod.write_story_copy(backend, plan, by_id, style, fmt, plist, words_rel,
                                       {"day": day, "n_places": len(plist)})
        if copy.get("hooks"):
            log("hooks: " + " | ".join(f"{h['text']} ({h['score']:.1f})" for h in copy["hooks"]))
    elif backend:
        copy = ai_mod.write_hook_and_caption(backend, {**plan, "overlays": [
            {"type": "location", "text": v} for v in places.values() if v] + (
            [{"type": "location", "text": location}] if location else [])}, by_id, style,
            want_hook=hook_cfg.get("mode") == "ai" and not hook,
            want_cta=(style["text"].get("cta") or {}).get("mode") == "ai")
    hook_text = hook or (hook_cfg.get("text") if hook_cfg.get("mode") == "text" else None) or copy.get("hook")
    if hook_text and hook_cfg.get("mode") != "off" or hook:
        h_start, h_dur = float(hook_cfg.get("start", 0.2)), float(hook_cfg.get("duration", 2.6))
        if arc:  # on screen from the third frame, held while the opening plays
            first = plan["segments"][0]
            h_start = 0.1
            h_dur = round(max(2.0, min(3.2, first["out_start"] + first["dur"] + 1.0)) - h_start, 3)
        plan["overlays"].append({"type": "hook", "text": hook_text, "start": h_start, "duration": h_dur})
        style["text"]["hook"]["mode"] = "on"
        plan["text"] = style["text"]
    if arc and st.get("format") == "list":
        style["text"]["location"]["mode"] = "off"  # the numbered place cards name every place
    add_location_overlays(plan, by_id, places, style, override=location)
    if arc:
        from . import formats, lyrics
        formats.apply(plan, st.get("format", "montage"), by_id, places_all, copy,
                      plan["segments"][0]["out_start"] + plan["segments"][0]["dur"])
        caps = lyrics.caption_overlays(words_rel, plan["duration"], str(st.get("captions", "auto")))
        if caps:
            plan["overlays"] += caps
            log(f"captions: {len(caps)} line(s) of the {words_rel.get('kind')}")
        plan.setdefault("story", {}).update({"hook_type": copy.get("hook_type"), "hooks": copy.get("hooks") or []})
    cta_cfg = style["text"].get("cta") or {}
    cta_text = cta_cfg.get("text") if cta_cfg.get("mode") == "text" else (
        copy.get("cta") if cta_cfg.get("mode") == "ai" else None)
    if cta_text:
        du = float(cta_cfg.get("duration", 2.2))
        st = max(0.0, plan["duration"] - du - 0.1)
        if all(o["start"] + o["duration"] <= st for o in plan["overlays"]):
            plan["overlays"].append({"type": "cta", "text": cta_text, "start": round(st, 3), "duration": du})

    rm_cfg = style.get("route_map") or {}
    if str(rm_cfg.get("mode", "off")) not in ("off", "none", "False", "false"):
        from . import routemap
        try:
            routemap.ensure_runtime()
            routemap.plan_route_map(plan, shots, by_id, rm_cfg, geocode=place_name)
        except ReelError as e:
            log(f"route map skipped: {e}")
    lab_cfg = style["text"].get("labels") or {}
    has_caps = any(o["type"] == "caption" for o in plan["overlays"])
    if lab_cfg.get("mode") == "ai" and backend and not has_caps and st.get("format") != "list":
        busy = [(o["start"], o["start"] + o["duration"]) for o in plan["overlays"] if o.get("mode") != "tracker"]
        cands = [sg for sg in plan["segments"] if sg["dur"] >= 0.75 and not sg.get("panel")
                 and not any(a < sg["out_start"] + sg["dur"] and sg["out_start"] < b for a, b in busy)]
        cands = cands[: int(lab_cfg.get("max", 8))]
        if cands:
            labels = ai_mod.write_labels(backend, [by_id.get(sg["shot_id"], {}).get("ai", {}) for sg in cands],
                                         [v for v in places.values() if v] + ([location] if location else []),
                                         style.get("caption", {}).get("tone", ""))
            for sg, lab in zip(cands, labels):
                if lab:
                    plan["overlays"].append({"type": "label", "text": lab, "start": round(sg["out_start"] + 0.05, 3),
                                             "duration": round(sg["dur"] - 0.12, 3)})
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    if out is None:
        name = inputs[0].resolve().name if len(inputs) == 1 else f"{inputs[0].resolve().name}+{len(inputs) - 1}"
        name = (extras or {}).get("name") or name
        out = default_out_dir() / f"{name}-{style['name']}-{stamp}.mp4"
    out = out.expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    plan["work"] = str(work)
    plan["sound"] = style.get("sound") or {}
    from .effects import mark_effects
    if arc and str(st.get("match_cuts", True)).lower() not in ("false", "off", "0"):
        from . import matchcut
        matchcut.apply(plan, by_id)
    mark_effects(plan, style)
    critic_report = None
    if arc and str(st.get("critic", "auto")) != "off":
        from . import critic
        critic_report = critic.review(plan, by_id, shots, style, backend if st.get("critic", "auto") in ("auto", "ai")
                                      else None, work)
    from . import grade as grade_mod
    grade_img = None
    try:
        if grade_mod.grade_plan(plan, by_id, style.get("grade") or {}, backend, work):
            grade_img = grade_mod.before_after(plan, by_id, out.with_suffix(".grade.jpg"))
    except KeyError as e:
        raise ReelError(str(e).strip("'\""))
    plan_path = out.with_suffix(".plan.json")
    write_json(plan_path, plan)
    sb = storyboard(plan, by_id, out.with_suffix(".storyboard.jpg"))
    exports = _exports(plan_path)
    caption_path = None
    if copy.get("caption") or copy.get("hashtags"):
        caption_path = out.with_suffix(".caption.txt")
        caption_path.write_text((copy.get("caption", "") + "\n\n" +
                                 " ".join("#" + h for h in copy.get("hashtags", []))).strip() + "\n")
    log(f"plan: {len(plan['segments'])} shots, {plan['duration']:.1f}s at {plan['tempo']:.0f} BPM -> {plan_path.name}")
    result = {"plan": str(plan_path), "storyboard": str(sb), "caption": str(caption_path) if caption_path else None,
              "grade": str(grade_img) if grade_img else None, **exports}
    if arc:
        result["idea"] = f"{st.get('format')}" + (f", hook: {copy.get('hook_type')}" if copy.get("hook_type") else "")
    if critic_report:
        cp = out.with_suffix(".critic.json")
        write_json(cp, critic_report)
        result["critic"] = str(cp)
        result["score"] = critic_report.get("score")
    if dry_run:
        return result
    render(plan, out, work, workers=workers)
    cover = export_cover(plan, out, out.with_suffix(".cover.jpg"))
    result.update({"video": str(out), "cover": str(cover) if cover else None})
    try:
        from .effects import check_beats
        result["beat_check"] = check_beats(out, plan)
    except Exception as e:
        log(f"beat check skipped ({e})")
    result.update(run_qa(out, plan))
    result["hook"] = next((o["text"] for o in plan["overlays"] if o["type"] == "hook"), None)
    if upload_copy and music:
        result["upload_video"] = str(export_no_audio(out))
    if music:
        result["sound"] = posting_note(plan)
        log(result["sound"])
    log(f"done: {out}")
    return result


def export_no_audio(video: Path) -> Path:
    """The reel without the music, to upload and then add the same sound in Instagram. With sound
    design, it keeps the effects and ambience (Instagram mixes this 'original audio' with the sound)."""
    stem = video.with_suffix(".sfx.wav")
    if stem.exists():
        dst = video.with_name(video.stem + ".nomusic.mp4")
        run(ffmpeg_base() + ["-i", str(video), "-i", str(stem), "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                             "-af", "loudnorm=I=-18:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "160k", "-shortest",
                             "-movflags", "+faststart", str(dst)])
        return dst
    dst = video.with_name(video.stem + ".noaudio.mp4")
    run(ffmpeg_base() + ["-i", str(video), "-map", "0:v", "-c", "copy", "-movflags", "+faststart", str(dst)])
    return dst


def posting_note(plan: dict) -> str:
    m = plan.get("music") or {}
    start = float(m.get("start") or 0)
    label = m.get("label") or Path(m.get("path") or "track").stem
    note = (f"sound: \"{label}\": in Instagram, add this sound and set it to start at "
            f"{int(start // 60)}:{start % 60:04.1f} so the cuts stay on the beat")
    snd = plan.get("sound") or {}
    if str(snd.get("sfx", "off")) != "off" or str(snd.get("ambience", "off")) != "off":
        note += ("; upload the .nomusic.mp4 (it keeps the sound effects), then in the volume settings keep "
                 "'original audio' around 40-60% under the song")
    return note


def render_plan(plan_path: Path, out: Path | None, workers: int = 2, text_motion: str | None = None) -> Path:
    plan, work = load_plan(plan_path)
    if text_motion:
        plan.setdefault("text", {})["motion"] = text_motion
    out = (out or plan_path.with_name(plan_path.name.replace(".plan.json", ".mp4"))).resolve()
    render(plan, out, work, workers=workers)
    export_cover(plan, out, out.with_suffix(".cover.jpg"))
    try:
        from .effects import check_beats
        check_beats(out, plan)
    except Exception as e:
        log(f"beat check skipped ({e})")
    run_qa(out, plan)
    log(f"done: {out}")
    return out


def run_qa(video: Path, plan: dict) -> dict:
    """qa.py after a render: never fails the render, returns {qa, qa_sheet} for the result."""
    if str((plan.get("qa") if isinstance(plan.get("qa"), str) else "on")) == "off":
        return {}
    try:
        from .qa import check
        rep = check(Path(video), plan)
        return {"qa": f"{rep['passed']}/{rep['total']} checks passed", "qa_sheet": rep.get("sheet"),
                "qa_failed": [c["check"] for c in rep["checks"] if not c["ok"]]}
    except Exception as e:
        log(f"qa skipped ({e})")
        return {}


def load_plan(plan_path: Path) -> tuple[dict, Path]:
    """Read a plan for rendering: re-tile edited durations and refresh swapped shots. -> (plan, work dir)."""
    plan = read_json(plan_path)
    if not plan:
        raise ReelError(f"could not read plan {plan_path}")
    # re-tile segments in case durations were edited by hand
    t = 0.0
    for i, s in enumerate(plan["segments"]):
        s["idx"], s["out_start"] = i, round(t, 4)
        t += float(s["dur"])
    plan["duration"] = round(t, 4)
    work = Path(plan.get("work") or plan_path.parent / ".tripshots-work")
    work.mkdir(parents=True, exist_ok=True)
    # allow swapping a shot by id after editing plan.json
    shots = {s["id"]: s for s in (read_json(work / "shots_scored.json", []) or [])}
    for s in plan["segments"]:
        sh = shots.get(s["shot_id"])
        if sh and (sh["src"] != s["src"] or (sh["kind"] == "video" and not sh["t0"] <= s.get("in", -1) < sh["t1"])):
            s.update({"src": sh["src"], "kind": sh["kind"], "src_w": sh["w"], "src_h": sh["h"],
                      "subject_x": sh.get("ai", {}).get("subject_x", 0.5)})
            ar = sh["w"] / max(sh["h"], 1)
            if sh["kind"] == "video":
                s.setdefault("speed", 1.0)
                s["in"], s["hdr"], s["transfer"] = sh["t0"], sh.get("hdr", False), sh.get("transfer")
                if s.get("layout") not in ("crop", "pan", "blur_fill", "fill"):
                    s["layout"] = "fill" if ar <= 0.75 else ("pan" if ar > 2.1 else "crop")
            else:
                s["still"] = sh["still"]
                s.pop("speed", None)
                s["layout"], s["kb"] = "kenburns", s.get("kb", "in")
    return plan, work


# ---------------------------------------------------------------- variants
def _variant_path(out: Path | None, k: int, n: int) -> Path | None:
    if out is None or n <= 1:
        return out
    out = Path(out)
    return out.with_name(f"{out.stem}-v{k + 1}{out.suffix or '.mp4'}")


def variants_sheet(results: list[dict], out: Path) -> Path | None:
    """One row per variant: its storyboard, labelled with its hook."""
    from PIL import Image, ImageDraw
    from .text import load_font
    rows = []
    for k, r in enumerate(results):
        sb = r.get("storyboard")
        if not sb or not Path(sb).exists():
            continue
        im = Image.open(sb).convert("RGB")
        w = 1400
        im = im.resize((w, int(im.height * w / im.width)))
        lab = Image.new("RGB", (w, 54), (12, 12, 12))
        ImageDraw.Draw(lab).text((14, 10), f"v{k + 1}" + (f'  ·  hook: "{r["hook"]}"' if r.get("hook") else ""),
                                 font=load_font(30, "bold"), fill=(255, 214, 0))
        rows += [lab, im]
    if not rows:
        return None
    sheet = Image.new("RGB", (1400, sum(r.height for r in rows)), (12, 12, 12))
    y = 0
    for r in rows:
        sheet.paste(r, (0, y))
        y += r.height
    sheet.save(out, "JPEG", quality=84)
    return out


def make_variants(n: int, inputs, music, style_name, out, *args, extras: dict | None = None, **kw) -> dict:
    """`make --variants N`: N versions with different opening shots, shot orders, transitions and hooks."""
    if n <= 1:
        return make(inputs, music, style_name, out, *args, extras=extras, **kw)
    results, hooks = [], []
    base_out = out
    for k in range(n):
        log(f"===== variant {k + 1}/{n} =====")
        ex = {**(extras or {}), "variant": k, "avoid_hooks": [h for h in hooks if h]}
        o = _variant_path(base_out, k, n)
        r = make(inputs, music, style_name, o, *args, extras=ex, **kw)
        if base_out is None and r.get("plan"):  # name the next ones after the first
            p = Path(r["plan"])
            base_out = p.with_name(p.name.replace(".plan.json", ".mp4"))
            new = _variant_path(base_out, 0, n)
            for key in ("plan", "storyboard", "grade", "caption", "video", "cover", "upload_video", "edl",
                        "storyboard_md"):
                if r.get(key) and Path(r[key]).exists():
                    q = Path(r[key])
                    dst = q.with_name(q.name.replace(base_out.stem, new.stem, 1))
                    q.replace(dst)
                    r[key] = str(dst)
        hooks.append(r.get("hook") or "")
        results.append(r)
    sheet = variants_sheet(results, _variant_path(base_out, 0, n).with_name(base_out.stem + ".variants.jpg"))
    log(f"{n} variants done" + (f"; compare them in {sheet.name}" if sheet else ""))
    return {"variants": results, "compare": str(sheet) if sheet else None}


# ---------------------------------------------------------------- clone
def clone(ref: str, inputs: list[Path], out: Path | None, style_name: str | None, backend_name: str | None,
          variants: int = 1, look: str | None = None, grade_strength: float | None = None,
          cookies: dict | None = None, keep_text: bool = False, dry_run: bool = False, workers: int = 2,
          source_opts: dict | None = None, upload_copy: bool | None = None, rescore: bool = False,
          text_preset: str | None = None, hype: bool = False, sound: dict | None = None,
          text_motion: str | None = None) -> dict:
    from . import clone as cl
    from . import grade as grade_mod
    from .config import HOME
    from .effects import check_beats, mark_effects
    style = load_style(style_name or "beat-montage")
    style.setdefault("velocity", {})["use"] = 0.0      # keep the reference's own pacing
    style.setdefault("popout", {})["use"] = 0.0
    style["shots"]["slowmo"] = True  # calm slots: 50 fps+ clips play in real slow motion, as reels like these do
    if not hype:
        style.setdefault("motion", {}).update({"freeze": False, "rgb_split": 0.0})
    if text_preset:
        style["text"]["preset"] = text_preset
    if text_motion:
        style["text"]["motion"] = text_motion
    style.setdefault("sound", {}).update({k: v for k, v in (sound or {}).items() if v is not None})
    shots, backend, work = prepare_shots(inputs, backend_name, source_opts=source_opts, rescore=rescore)
    by_id = {s["id"]: s for s in shots}
    refd = cl.analyze_reference(ref, HOME / "clone", cookies)
    if len(refd["shots"]) < 2:
        raise ReelError("the reference has fewer than 2 shots: nothing to clone (is it one continuous clip?)")
    slots = cl.describe_reference(refd, backend)["shots"]
    # the user's places, for rewriting place names in the text (one lookup per area, cached)
    places, seen = {}, {}
    for s in sorted(shots, key=lambda s: -float(s.get("ai", {}).get("score", 5)))[:60]:
        if s.get("gps"):
            k = (round(s["gps"][0], 2), round(s["gps"][1], 2))
            if k not in seen:
                seen[k] = place_name(*s["gps"])
            places[s["id"]] = seen[k]
    rdir = Path(refd["dir"])
    texts = {}
    from .diversity import scene_groups
    groups = scene_groups(shots)
    n_moments = len(set(groups.values()))
    if n_moments < len(shots):
        log(f"{len(shots)} shots are {n_moments} different moments (bursts, the photo and the clip of one view): "
            "a clone uses each moment once")
    fallback = cl.heuristic_match(slots, refd["shots"], shots, refd, groups, depth=12)
    motion = cl.ref_motion(refd)
    if backend:
        try:
            match, texts = cl.ai_match(slots, refd["shots"], shots, places, backend, rdir, refd, groups)
        except Exception as e:
            log(f"AI matching failed ({e}); matching by light, colour and tags instead")
            match = fallback
    else:
        match = fallback
        if any(sl.get("text") for sl in slots) and not keep_text:
            log("no AI backend: the reference's on-screen text is left out (use --keep-text to copy it as is)")
    # colour: the reference's grade becomes a look, unless you choose one
    if not look:
        frames = [cv2_rgb(s["frame"]) for s in refd["shots"] if s.get("frame")]
        frames = [f for f in frames if f is not None]
        if frames:
            name = "clone-" + rdir.name.replace("ref_", "")[:8]
            grade_mod.save_look(grade_mod.look_from_images(frames, name, "Colour of the cloned reel."), name)
            look = name
            style["grade"]["match"] = "full"  # a clone takes on the reference's mood, not a hint of it
    style["grade"]["look"] = look or style["grade"].get("look", "auto")
    if grade_strength is not None:
        style["grade"]["strength"] = float(grade_strength)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    if out is None:
        out = default_out_dir() / f"clone-{inputs[0].resolve().name}-{stamp}.mp4"
    out = Path(out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    is_link = bool(re.match(r"https?://", ref))
    if upload_copy is None:
        upload_copy = is_link
    results = []
    for v in range(max(1, variants)):
        o = _variant_path(out, v, variants)
        plan = cl.build_clone_plan(refd, slots, match, texts, shots, style, variant=v, keep_text=keep_text,
                                   groups=groups, fallback=fallback, motion=motion)
        plan["work"] = str(work)
        plan["sound"] = style.get("sound") or {}
        plan["music"]["label"] = "the original reel's sound" if is_link else Path(ref).stem
        plan["music"]["source_url"] = ref if is_link else None
        mark_effects(plan, style)
        r = {}
        if grade_mod.grade_plan(plan, by_id, style.get("grade") or {}, backend, work):
            r["grade"] = str(grade_mod.before_after(plan, by_id, o.with_suffix(".grade.jpg")))
        if backend:
            copy = ai_mod.write_hook_and_caption(backend, plan, by_id, style, want_hook=False)
            if copy.get("caption") or copy.get("hashtags"):
                cp = o.with_suffix(".caption.txt")
                cp.write_text((copy.get("caption", "") + "\n\n" +
                               " ".join("#" + h for h in copy.get("hashtags", []))).strip() + "\n")
                r["caption"] = str(cp)
        plan_path = o.with_suffix(".plan.json")
        write_json(plan_path, plan)
        r.update(_exports(plan_path))
        r.update({"plan": str(plan_path), "storyboard": str(storyboard(plan, by_id, o.with_suffix(".storyboard.jpg"))),
                  "compare": str(cl.compare_sheet(refd, plan, by_id, o.with_suffix(".clone.jpg"))),
                  "hook": next((x["text"] for x in plan["overlays"] if x["type"] == "hook"), None),
                  "texts": [x["text"] for x in plan["overlays"]]})
        log(f"clone v{v + 1}: {len(plan['segments'])} slots, {plan['duration']:.1f}s, "
            f"{len(set(s['shot_id'] for s in plan['segments']))} different shots of yours")
        if not dry_run:
            render(plan, o, work, workers=workers)
            cover = export_cover(plan, o, o.with_suffix(".cover.jpg"))
            r.update({"video": str(o), "cover": str(cover) if cover else None})
            if upload_copy and plan["music"].get("path"):
                r["upload_video"] = str(export_no_audio(o))
                r["sound"] = ("post the .noaudio.mp4 and add the original reel's sound in Instagram, starting at "
                              "0:00, so the cuts stay on its beat")
            try:
                r["beat_check"] = check_beats(o, plan)
            except Exception as e:
                log(f"beat check skipped ({e})")
            r.update(run_qa(o, plan))
        results.append(r)
    res = results[0] if len(results) == 1 else {"variants": results}
    if len(results) > 1:
        sheet = variants_sheet(results, out.with_name(out.stem + ".variants.jpg"))
        res["compare"] = str(sheet) if sheet else None
    return res


def cv2_rgb(path):
    import cv2
    im = cv2.imread(str(path))
    return None if im is None else cv2.cvtColor(im, cv2.COLOR_BGR2RGB)
