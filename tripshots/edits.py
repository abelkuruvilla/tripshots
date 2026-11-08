"""Send a reel to Instagram's Edits app (Mac) to finish and post it there.

TripShots keeps doing what only it can do (picking and timing the shots, colour, motion, transitions,
split screens, maps, titles behind the skyline, sound design) and bakes that into the picture. What Edits
does well stays editable in Edits: the text, the sound effects as their own track, and the song (from
Instagram's own library, so the post uses the licensed sound).

    tripshots edits package NAME.plan.json      # -> NAME.edits/ (clips, text, audio, manifest.json)
    tripshots edits tools                        # what this Edits version's automation server offers
    tripshots edits probe                        # draft a mapping from our steps to those tools
    tripshots edits push NAME.edits              # build the timeline in Edits (needs a confirmed mapping)

Edits' automation server (Settings > Automation, Mac only) is undocumented and changes with app updates,
so TripShots never assumes its tool names: `probe` reads them from the running app and writes a draft
mapping (~/.tripshots/edits/profile.json) that a person or an agent confirms. Agents connected to both
TripShots and Edits can also assemble the package themselves from manifest.json (skills/tripshots/SKILL.md).
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
import re
import shutil
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import numpy as np

from .config import HOME, OUT_FPS, OUT_H, OUT_W
from .util import ReelError, ffmpeg_base, is_mac, log, read_json, run, write_json

MANIFEST_VERSION = 1
EDITS_DIR = HOME / "edits"
PROFILE = EDITS_DIR / "profile.json"
DEFAULT_URL = "http://127.0.0.1:19501/mcp"
# Edits is sandboxed: it can only open files inside its own container
STAGE = Path.home() / "Library/Containers/com.burbn.basel.mac/Data/tmp/tripshots"
NATIVE_TYPES = ("hook", "location", "cta", "label", "caption")


# ================================================================== package
def package(plan_path: Path, out_dir: Path | None = None, clips: bool = True, stage: bool | None = None,
            workers: int = 2) -> dict:
    """Render the picture (everything except native text and audio) and write an Edits package."""
    from . import sound
    from .pipeline import load_plan
    from .render import render
    plan_path = Path(plan_path).resolve()
    plan, work = load_plan(plan_path)
    name = plan_path.name.replace(".plan.json", "")
    pkg = (Path(out_dir) if out_dir else plan_path.with_name(f"{name}.edits")).resolve()
    if pkg.exists():
        shutil.rmtree(pkg)
    (pkg / "text").mkdir(parents=True)

    # 1. the picture: no music, no sound design, native text laid out but not drawn
    pic_plan = copy.deepcopy(plan)
    pic_plan["sound"] = {"sfx": "off", "ambience": "off"}
    pic_plan["music"] = {}
    info: dict = {}
    log("rendering the picture for Edits (text and audio stay separate)...")
    tmp = pkg / "picture.tmp.mp4"
    render(pic_plan, tmp, work, workers=workers, native_text=True, info=info)
    picture = pkg / "picture.mp4"
    run(ffmpeg_base() + ["-i", str(tmp), "-map", "0:v", "-c:v", "copy", "-an", "-movflags", "+faststart",
                         str(picture)])
    tmp.unlink(missing_ok=True)
    texts = info.get("texts")

    # 2. the shots as separate clips, cut at the planned frames (transitions are split across the cut,
    #    so the clips play back seamlessly when laid end to end)
    clip_rows = []
    if clips:
        (pkg / "clips").mkdir()
        from . import encode
        for i, s in enumerate(plan["segments"]):
            f = pkg / "clips" / f"{i + 1:02d}-{s.get('shot_id') or 'shot'}.mp4"
            start, n = float(s["out_start"]), int(round(float(s["dur"]) * OUT_FPS))
            run(ffmpeg_base() + ["-i", str(picture), "-vf", f"trim=start_frame={int(round(start * OUT_FPS))}:"
                                 f"end_frame={int(round(start * OUT_FPS)) + n},setpts=PTS-STARTPTS",
                                 "-an", *encode.args("final"), "-r", str(OUT_FPS), "-movflags", "+faststart", str(f)])
            clip_rows.append({"file": f"clips/{f.name}", "start": round(start, 4), "duration": round(n / OUT_FPS, 4),
                              "shot_id": s.get("shot_id"), "source": Path(str(s.get("src") or "")).name or None,
                              "transition_out": s.get("trans_out") or ("in-camera whip" if s.get("incam_out") else None),
                              "note": s.get("note") or ""})

    # 3. text: as data (to add as Edits text) and as transparent PNGs (TripShots' exact look)
    text_rows, baked = [], []
    if texts is not None:
        for k, spec in enumerate(texts.specs):
            el = texts.built.get(k)
            if el is None:
                continue
            if texts.baked(k):
                baked.append(f"{spec['type']}: {spec.get('text')} (drawn behind the skyline)")
                continue
            row = {"type": spec["type"], "text": spec.get("text"), "start": round(float(spec["start"]), 3),
                   "duration": round(float(spec["duration"]), 3), "animation": el.anim}
            png = _text_png(el, pkg / "text" / f"{len(text_rows) + 1:02d}-{spec['type']}.png")
            if png:
                row.update({"image": f"text/{png[0].name}", "box": png[1]})
            if spec["type"] == "location":
                row.update({k2: spec.get(k2) for k2 in ("main", "sub", "coords", "gps") if spec.get(k2)})
            text_rows.append(row)
    for o in plan.get("overlays") or []:
        if o.get("type") == "map":
            baked.append(f"route map ({o.get('mode')})")

    # 4. audio: the sound design as its own track, and the song (to swap for Instagram's copy)
    audio_rows = []
    cfg = plan.get("sound") or {}
    if str(cfg.get("sfx", "on")) != "off" or str(cfg.get("ambience", "on")) != "off":
        try:
            res = sound.design(plan, sound.text_events_from(texts) if texts else [])
            if res["cues"] or res["ambience"]:
                sfx = pkg / "sound-effects.wav"
                sound.write_wav(sfx, res["stem"][: int((float(plan["duration"]) + 0.05) * sound.SR)])
                audio_rows.append({"role": "sound effects + ambience", "file": sfx.name, "start": 0.0,
                                   "cues": [{"t": c["t"], "role": c["role"], "why": c["why"]} for c in res["cues"]],
                                   "licenses": sorted({str(v.get("license")) for v in res["sources"].values()})})
        except Exception as e:
            log(f"sound effects skipped ({e})")
    music = plan.get("music") or {}
    music_row = None
    if music.get("path") and Path(music["path"]).exists():
        mf = pkg / "music.m4a"
        dur, fo = float(plan["duration"]), float(music.get("fade_out", 0.8))
        run(ffmpeg_base() + ["-ss", f"{float(music.get('start', 0)):.3f}", "-t", f"{dur:.3f}", "-i", music["path"],
                             "-af", f"afade=t=out:st={max(0.0, dur - fo):.3f}:d={fo:.3f}", "-c:a", "aac", "-b:a",
                             "192k", str(mf)])
        music_row = {"title": music.get("label") or Path(music["path"]).stem, "file": mf.name,
                     "source": music.get("source_url") or Path(music["path"]).name,
                     "song_start": round(float(music.get("start", 0)), 3), "reel_start": 0.0,
                     "tempo": plan.get("tempo"),
                     "tip": "Prefer the same song from Edits' / Instagram's library, starting at song_start, "
                            "so the post uses the licensed sound; the cuts are on its beats"}

    for extra in (".storyboard.jpg", ".cover.jpg", ".caption.txt"):
        src = plan_path.with_name(name + extra)
        if src.exists():
            shutil.copy2(src, pkg / src.name)
    manifest = {
        "tripshots_edits": MANIFEST_VERSION, "created": datetime.now().isoformat(timespec="seconds"),
        "name": name, "plan": str(plan_path), "width": OUT_W, "height": OUT_H, "fps": OUT_FPS,
        "duration": round(float(plan["duration"]), 4), "tempo": plan.get("tempo"),
        "beats": [round(float(b), 3) for b in plan.get("beats") or []],
        "picture": {"file": picture.name, "contains": ["colour grade", "motion and transitions", "effects",
                                                       "split screens", *baked]},
        "clips": clip_rows, "texts": text_rows, "audio": audio_rows, "music": music_row,
        "caption": (plan_path.with_name(name + ".caption.txt").read_text().strip()
                    if plan_path.with_name(name + ".caption.txt").exists() else None),
        "assemble": [
            "New 9:16 project.",
            "Video: either picture.mp4 at 0:00, or the clips in order, each at its 'start' (they butt together).",
            "Text: each entry of 'texts' as Edits text at its start for its duration (or its PNG at 'box').",
            "Audio: sound-effects.wav at 0:00.",
            "Music: the song from Edits' library starting at music.song_start (or music.m4a at 0:00).",
        ],
    }
    write_json(pkg / "manifest.json", manifest)
    (pkg / "README.txt").write_text(_readme(manifest))
    res = {"package": str(pkg), "manifest": str(pkg / "manifest.json"), "picture": str(picture),
           "clips": len(clip_rows), "texts": len(text_rows), "audio": [a["file"] for a in audio_rows],
           "music": music_row and music_row["title"]}
    if stage is None:
        stage = is_mac() and STAGE.parent.exists()
    if stage:
        res["staged"] = str(stage_package(pkg))
    log(f"Edits package: {pkg.name} ({len(clip_rows)} clips, {len(text_rows)} texts)"
        + (f", staged for Edits in {res['staged']}" if res.get("staged") else ""))
    return res


def _text_png(el, out: Path):
    """One text element in its final state as a transparent PNG, cropped; box normalised to the frame."""
    from PIL import Image
    canvas = Image.new("RGBA", (OUT_W, OUT_H), (0, 0, 0, 0))
    for sp in el.sprites:
        im = Image.fromarray((np.clip(sp.img, 0, 1) * 255).astype(np.uint8), "RGBA")
        layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        layer.paste(im, (int(round(sp.x)), int(round(sp.y))))
        canvas = Image.alpha_composite(canvas, layer)
    bb = canvas.getbbox()
    if not bb:
        return None
    canvas.crop(bb).save(out)
    x0, y0, x1, y1 = bb
    return out, {"x": round(x0 / OUT_W, 4), "y": round(y0 / OUT_H, 4),
                 "w": round((x1 - x0) / OUT_W, 4), "h": round((y1 - y0) / OUT_H, 4)}


def _readme(m: dict) -> str:
    L = [f"TripShots -> Edits package: {m['name']}", "", f"Length {m['duration']:.2f} s, {m['width']}x{m['height']}, "
         f"{m['fps']} fps" + (f", {m['tempo']:.0f} BPM" if m.get("tempo") else ""), "", "Build it in Edits:"]
    L += [f"  {i}. {s}" for i, s in enumerate(m["assemble"], 1)]
    if m["texts"]:
        L += ["", "Text:"] + [f"  {t['start']:6.2f}-{t['start'] + t['duration']:.2f}s  {t['type']:<9} {t['text']}"
                              for t in m["texts"]]
    if m["music"]:
        L += ["", f"Music: \"{m['music']['title']}\" from {m['music']['song_start']:.2f}s of the song."]
    if m["clips"]:
        L += ["", "Clips:"] + [f"  {c['start']:6.2f}s  {c['file']}  ({c.get('source') or ''})" for c in m["clips"]]
    return "\n".join(L) + "\n"


def stage_package(pkg: Path, root: Path | None = None) -> Path:
    """Copy a package where the sandboxed Edits app can open it."""
    dst = Path(os.environ.get("TRIPSHOTS_EDITS_STAGE") or root or STAGE) / pkg.name
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(pkg, dst)
    return dst


# ================================================================== talking to Edits
def _url() -> str:
    return os.environ.get("TRIPSHOTS_EDITS_URL") or DEFAULT_URL


@asynccontextmanager
async def _session(url: str | None = None, token: str | None = None):
    from mcp import ClientSession
    url = url or _url()
    token = token if token is not None else os.environ.get("TRIPSHOTS_EDITS_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client
    except ImportError:  # mcp 1.x
        from mcp.client.streamable_http import streamablehttp_client
        async with streamablehttp_client(url, headers=headers) as (r, w, _):
            async with ClientSession(r, w) as s:
                await s.initialize()
                yield s
        return
    async with create_mcp_http_client(headers=headers) as hc:
        async with streamable_http_client(url, http_client=hc) as streams:
            async with ClientSession(streams[0], streams[1]) as s:
                await s.initialize()
                yield s


def _schema(t) -> dict:
    return getattr(t, "inputSchema", None) or getattr(t, "input_schema", None) or {}


async def _list_tools(url=None, token=None) -> list[dict]:
    async with _session(url, token) as s:
        res = await s.list_tools()
        return [{"name": t.name, "description": (t.description or "").strip(), "params": _schema(t)}
                for t in (res.tools if hasattr(res, "tools") else res)]


def tools(url=None, token=None) -> dict:
    """What the running Edits app offers (saved to ~/.tripshots/edits/tools.json)."""
    try:
        ts = asyncio.run(_list_tools(url, token))
    except Exception as e:
        raise ReelError(f"can't reach Edits at {url or _url()} ({type(e).__name__}: {e}). Open Edits, sign in, "
                        "turn on Settings > Automation > Automation Server, and set TRIPSHOTS_EDITS_TOKEN to its token")
    EDITS_DIR.mkdir(parents=True, exist_ok=True)
    write_json(EDITS_DIR / "tools.json", ts)
    return {"url": url or _url(), "count": len(ts), "saved": str(EDITS_DIR / "tools.json"),
            "tools": [t["name"] for t in ts]}


# ------------------------------------------------------------------ mapping our steps to their tools
STEPS = {  # step: (words in the tool name/description, the arguments it needs)
    "new_project": (["create project", "new project", "createproject", "newproject"], []),
    "import": (["import", "add media", "addmedia", "upload", "load media"], ["file"]),
    "add_clip": (["add clip", "addclip", "insert clip", "place clip", "add video", "append clip", "timeline"],
                 ["media", "start"]),
    "add_text": (["add text", "addtext", "text", "title", "caption"], ["text", "start"]),
    "add_audio": (["add audio", "addaudio", "sound", "audio", "sfx", "music"], ["media", "start"]),
    "add_image": (["overlay", "sticker", "image", "add image", "place overlay"], ["media", "start"]),
}
ARGS = {
    "file": ["path", "filepath", "file", "url", "uri", "filename", "source"],
    "media": ["mediaid", "assetid", "media", "asset", "clipid", "id", "itemid"],
    "start": ["start", "starttime", "at", "time", "offset", "position", "timelinestart", "startseconds", "startms"],
    "duration": ["duration", "length", "durationseconds", "durationms"],
    "text": ["text", "content", "string", "value", "title"],
    "project": ["projectid", "project"],
}
PLACEHOLDER = {"file": "{file}", "media": "{media_id}", "start": "{start}", "duration": "{duration}",
               "text": "{text}", "project": "{project_id}"}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _match_args(params: dict) -> dict:
    props = (params or {}).get("properties", {})
    out = {}
    for ours, names in ARGS.items():
        for p in props:
            if _norm(p) in names and p not in out.values():
                out[ours] = p
                break
    return out


def draft_profile(tool_list: list[dict]) -> dict:
    """Best guess at which Edits tool does each step, with the argument names filled in."""
    steps, notes = {}, []
    for step, (words, need) in STEPS.items():
        best, best_score, best_args = None, 0.0, {}
        for t in tool_list:
            hay = (t["name"] + " " + t["description"][:200]).lower()
            nm = _norm(t["name"])
            score = sum(3 if _norm(w) in nm else (1 if w in hay else 0) for w in words)
            args = _match_args(t["params"])
            if score == 0 or not all(n in args for n in need):
                continue  # a tool must look like the step by name, not just take the right arguments
            score += len(args)
            if score > best_score:
                best, best_score, best_args = t, score, args
        if best is None:
            notes.append(f"{step}: no tool found")
            continue
        props = best["params"].get("properties", {})
        ms = any("ms" in _norm(best_args.get(k, "")) for k in ("start", "duration"))
        steps[step] = {"tool": best["name"], "args": {theirs: PLACEHOLDER[ours] for ours, theirs in best_args.items()},
                       "time_unit": "ms" if ms else "s", "save": {"media_id": "id"} if step == "import" else
                       ({"project_id": "id"} if step == "new_project" else {}),
                       "other_params": [p for p in props if p not in best_args.values()]}
    return {"version": 1, "confirmed": False, "url": _url(), "steps": steps, "notes": notes,
            "how_to_confirm": "check each step's tool and args against tools.json, fill other required params, "
                              "then set \"confirmed\": true"}


def probe(url=None, token=None) -> dict:
    t = tools(url, token)
    prof = draft_profile(read_json(EDITS_DIR / "tools.json", []))
    out = PROFILE if not PROFILE.exists() else EDITS_DIR / "profile.draft.json"
    write_json(out, prof)
    return {**{k: t[k] for k in ("url", "count")}, "profile": str(out),
            "mapped": {k: v["tool"] for k, v in prof["steps"].items()}, "notes": prof["notes"]}


# ------------------------------------------------------------------ push
def _fill(tpl, vals: dict, unit: str):
    if isinstance(tpl, dict):
        return {k: _fill(v, vals, unit) for k, v in tpl.items()}
    if isinstance(tpl, list):
        return [_fill(v, vals, unit) for v in tpl]
    if isinstance(tpl, str):
        m = re.fullmatch(r"\{(\w+)\}", tpl)
        if m and m.group(1) in vals:
            v = vals[m.group(1)]
            if m.group(1) in ("start", "duration") and unit == "ms":
                return int(round(float(v) * 1000))
            if m.group(1) in ("start", "duration") and unit == "frames":
                return int(round(float(v) * OUT_FPS))
            return v
        return re.sub(r"\{(\w+)\}", lambda mm: str(vals.get(mm.group(1), mm.group(0))), tpl)
    return tpl


def _result_json(res):
    for c in getattr(res, "content", []) or []:
        if getattr(c, "type", "") == "text":
            try:
                return json.loads(c.text)
            except (json.JSONDecodeError, TypeError):
                return {"text": c.text}
    sc = getattr(res, "structuredContent", None) or getattr(res, "structured_content", None)
    return sc or {}


def _dig(d, path: str):
    for k in path.split("."):
        if isinstance(d, dict) and k in d:
            d = d[k]
        else:
            return None
    return d


async def _push(pkg: Path, prof: dict, mode: str, music: str, text_as: str, url, token) -> dict:
    m = read_json(pkg / "manifest.json")
    steps = prof["steps"]
    done, ids = [], {}

    async with _session(url or prof.get("url"), token) as s:
        async def call(step: str, vals: dict):
            st = steps[step]
            args = _fill(st.get("args", {}), {**ids, **vals}, st.get("time_unit", "s"))
            args.update(st.get("fixed", {}))
            res = await s.call_tool(st["tool"], args)
            if getattr(res, "is_error", None) or getattr(res, "isError", None):
                raise ReelError(f"Edits {st['tool']} failed: {_result_json(res)}")
            out = _result_json(res)
            for var, path in (st.get("save") or {}).items():
                v = _dig(out, path) if isinstance(out, dict) else None
                if v is not None:
                    ids[var] = v
            done.append(f"{st['tool']} {json.dumps(vals, default=str)[:80]}")
            return out

        def f(rel):  # files as Edits must see them (its sandbox)
            return str((pkg / rel).resolve())

        if "new_project" in steps:
            await call("new_project", {})
        if mode == "clips" and m["clips"]:
            for c in m["clips"]:
                await call("import", {"file": f(c["file"])})
                await call("add_clip", {"start": c["start"], "duration": c["duration"]})
        else:
            await call("import", {"file": f(m["picture"]["file"])})
            await call("add_clip", {"start": 0.0, "duration": m["duration"]})
        for t in m["texts"]:
            if text_as == "image" and t.get("image") and "add_image" in steps:
                await call("import", {"file": f(t["image"])})
                await call("add_image", {"start": t["start"], "duration": t["duration"]})
            elif "add_text" in steps:
                await call("add_text", {"text": t["text"], "start": t["start"], "duration": t["duration"]})
        if "add_audio" in steps:
            for a in m["audio"]:
                await call("import", {"file": f(a["file"])})
                await call("add_audio", {"start": a["start"], "duration": m["duration"]})
            if m.get("music") and music == "file":
                await call("import", {"file": f(m["music"]["file"])})
                await call("add_audio", {"start": 0.0, "duration": m["duration"]})
    left = []
    if m.get("music") and music == "library":
        left.append(f"add \"{m['music']['title']}\" from Edits' library, starting {m['music']['song_start']:.2f}s "
                    "into the song (or push again with --music file)")
    if m["texts"] and "add_text" not in steps and not (text_as == "image" and "add_image" in steps):
        left.append("add the text yourself (see README.txt): no text tool mapped")
    return {"package": str(pkg), "calls": len(done), "steps": done, "left_to_do": left,
            "next": "check it in Edits, then export / post from there"}


def push(package_dir: Path, mode: str = "clips", music: str = "library", text_as: str = "text",
         url: str | None = None, token: str | None = None, profile: Path | None = None) -> dict:
    """Build the timeline in Edits from a package, using the confirmed tool mapping."""
    pkg = Path(package_dir).resolve()
    if not (pkg / "manifest.json").exists():
        raise ReelError(f"not an Edits package: {pkg} (make one with `tripshots edits package <plan>`)")
    prof = read_json(Path(profile) if profile else PROFILE)
    if not prof:
        raise ReelError("no Edits tool mapping yet: run `tripshots edits probe` with Edits open, check "
                        f"{PROFILE}, and set \"confirmed\": true")
    if not prof.get("confirmed"):
        raise ReelError(f"the Edits tool mapping in {profile or PROFILE} isn't confirmed yet: check each step against "
                        f"{EDITS_DIR / 'tools.json'} and set \"confirmed\": true")
    missing = [s for s in ("import", "add_clip") if s not in prof.get("steps", {})]
    if missing:
        raise ReelError(f"the mapping has no {', '.join(missing)} step")
    if is_mac() and STAGE.parent.exists() and not str(pkg).startswith(str(STAGE.parent)):
        pkg = stage_package(pkg)  # Edits can only open files in its own container
    return asyncio.run(_push(pkg, prof, mode, music, text_as, url, token))
