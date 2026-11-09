"""TripShots as an MCP server: any AI agent (Claude Desktop, Claude Code, OpenClaw, Cursor, ...) can find
footage, build a reel, look at it, change it and render it.

    tripshots mcp                      # stdio (Claude Desktop / Claude Code start it themselves)
    tripshots mcp --http 0.0.0.0:8765  # remote agents (needs TRIPSHOTS_MCP_TOKEN: Authorization: Bearer <token>)

Long steps (finding faces, analysing footage, rendering) run as background jobs: the tool waits up to
~50 s and otherwise returns a job id to poll with `job_status`.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import re
import sys
from pathlib import Path

try:  # mcp 2.x
    from mcp.server.mcpserver import Image, MCPServer
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as MCPServer, Image  # type: ignore

from . import jobs
from .config import HOME, list_styles, load_env
from .util import ReelError

WAIT = 50.0  # seconds a tool blocks before handing back a job id

INSTRUCTIONS = """TripShots turns the user's own travel photos and clips into beat-synced Instagram Reels
(1080x1920). Nothing is generated: every frame is the user's footage.

Workflow for a request like "a reel about my days in Yellowstone" or "a reel of the photos I'm in":
1. `status` once: footage folders, known people, AI backend. If no footage folders are set, ask the user
   where their footage lives and call `set_footage_folders`.
2. Turn the request into a search: `find_footage` (place / people / dates / kinds). For "me / I / my photos",
   use people=["me"]. If "me" (or a named person) isn't known yet, ask for 2-5 photos of them and call
   `people_add`, or run `people_discover` and ask the user which cluster is them (`people_name`).
   Unsure which trip they mean? `list_trips` shows dates and places.
3. Look at the contact sheet `find_footage` returns. Too few files (< ~8) makes a thin reel: widen the search.
4. `make_reel` with the selection id (dry_run=true first). Pick music from `list_music` or ask; without
   music the reel is silent at 100 BPM. Choose a style from `list_styles` to match the mood.
5. Look at the storyboard image. Fix weak slots with `edit_plan` (swap shots from `shot_candidates`,
   change the hook text: 7 words max, transitions), then `render_reel`.
6. Give the user the mp4 path, cover and caption. Offer one concrete tweak.
Make the creative calls yourself; the user is not a video editor."""

mcp = MCPServer("tripshots", instructions=INSTRUCTIONS)


# ------------------------------------------------------------------ helpers
def _img(path: str | Path | None, max_w: int = 1400) -> Image | None:
    """A JPEG small enough for a tool result."""
    if not path or not Path(path).exists():
        return None
    from PIL import Image as PImage
    with PImage.open(path) as im:
        im = im.convert("RGB")
        if im.width > max_w:
            im = im.resize((max_w, int(im.height * max_w / im.width)))
        b = io.BytesIO()
        im.save(b, "JPEG", quality=80)
    return Image(data=b.getvalue(), format="jpeg")


def _plan(path: str) -> Path:
    """Plan tools only touch TripShots plan files."""
    p = Path(path).expanduser()
    if not p.name.endswith(".plan.json") or not p.is_file():
        raise ReelError(f"not a TripShots plan file: {path}")
    return p


def _txt(obj) -> str:
    return obj if isinstance(obj, str) else json.dumps(obj, indent=2, default=str)


def _out(obj, *images) -> list:
    return [_txt(obj)] + [i for i in images if i is not None]


async def _run_job(args: list[str], kind: str, label: str, wait: float = WAIT) -> dict:
    jid = jobs.start(args, kind, label)
    return await asyncio.to_thread(jobs.wait, jid, wait)


def _finished(st: dict) -> list:
    """Job status -> text + the images an agent should look at."""
    res = st.get("result") if st.get("state") == "done" else None
    imgs = []
    if isinstance(res, dict):
        if st["kind"] == "make":
            for v in (res.get("variants") or [res]):
                imgs.append(_img(v.get("storyboard")))
            imgs.append(_img(res.get("compare")))
            md = res.get("storyboard_md")
            if md and Path(md).exists():
                res["storyboard_table"] = Path(md).read_text()
        elif st["kind"] == "render":
            imgs.append(_img(res.get("cover"), 600))
            cap = res.get("caption")
            if cap and Path(cap).exists():
                res["caption_text"] = Path(cap).read_text()
        elif st["kind"] == "analyze" and res.get("media"):
            res["next"] = "search it with search_media, or read media.jsonl (one tripshots.media/1 record per file)"
        elif st["kind"] == "edits":
            m = Path(res.get("manifest", ""))
            if m.exists():
                res["manifest_content"] = json.loads(m.read_text())
        elif st["kind"] == "find" and res.get("sheet"):
            imgs.append(_img(res["sheet"]))
        elif st["kind"] == "discover" and res.get("sheet"):
            imgs.append(_img(res["sheet"]))
    elif st.get("state") == "running":
        st["next"] = f"still working: call job_status('{st['id']}') again"
    return _out(st, *imgs)


# ------------------------------------------------------------------ setup
@mcp.tool()
async def status() -> str:
    """What TripShots knows: footage folders, music folders, people it can recognise, AI backend, where reels go,
    recent jobs. Call this first."""
    from . import catalog, people
    from .ai import get_backend
    try:
        be = get_backend()
        backend = be.name if be else "none (heuristics only)"
    except ReelError as e:
        backend = f"not ready: {e}"
    return _txt({"footage_folders": [str(p) for p in catalog.footage_roots()],
                 "music_folders": _music_dirs(), "reels_folder": os.environ.get("TRIPSHOTS_OUT"),
                 "people": people.list_people(), "face_models": people.available()[1], "ai_backend": backend,
                 "styles": sorted(list_styles()), "recent_jobs": jobs.recent(5)})


@mcp.tool()
async def set_footage_folders(folders: list[str]) -> str:
    """Remember where the user's photos/videos live (searched recursively). Replaces the current list."""
    from . import catalog
    return _txt({"footage_folders": await asyncio.to_thread(catalog.set_footage_roots, folders)})


@mcp.tool()
async def set_folders(reels_folder: str | None = None, music_folders: list[str] | None = None) -> str:
    """Where finished reels are written, and where the user keeps music for reels."""
    from .config import write_env
    upd = {}
    if reels_folder:
        upd["TRIPSHOTS_OUT"] = str(Path(reels_folder).expanduser())
    if music_folders is not None:
        upd["TRIPSHOTS_MUSIC"] = os.pathsep.join(str(Path(m).expanduser()) for m in music_folders)
    write_env(upd)
    return _txt({"reels_folder": os.environ.get("TRIPSHOTS_OUT"), "music_folders": _music_dirs()})


# ------------------------------------------------------------------ footage
@mcp.tool()
async def list_trips(folders: list[str] | None = None) -> list:
    """The user's footage grouped into trips: dates, number of days, places (from GPS), photo/video counts and
    per-day places. Use it to resolve "my Iceland trip", "last summer", "the day at the lake"."""
    st = await _run_job(["trips", "--", *(folders or [])], "trips", "trips")
    return _finished(st)


@mcp.tool()
async def find_footage(place: str | None = None, people: list[str] | None = None, date_from: str | None = None,
                       date_to: str | None = None, near_lat: float | None = None, near_lon: float | None = None,
                       radius_km: float = 10, kinds: str = "both", any_people: bool = False,
                       whole_days: bool = True, text: str | None = None, folders: list[str] | None = None,
                       label: str | None = None) -> list:
    """Find photos/videos and save them as a selection for make_reel. Returns counts, days, places, people,
    a selection id ("sel:xxxx") and a contact sheet to check.

    place: a real place name, as specific as helps ("Yellowstone National Park", "Lisbon", "Moraine Lake").
      Matches GPS inside the place's outline, folder/file names, and known place names.
    people: who must appear, e.g. ["me"], ["me", "mom"] (any_people=true for either). Faces are recognised on
      this computer; unknown names need people_add / people_name first.
    date_from/date_to: YYYY-MM-DD. kinds: both | photo | video.
    whole_days: also include same-day files without GPS (phone clips) during the place's hours (default true).
    text: words that must appear in the folder/file/place name."""
    args = ["find", "--sheet", "--kind", kinds]
    if place:
        args += ["--place", place]
    if near_lat is not None and near_lon is not None:
        args += ["--near", f"{near_lat},{near_lon}", "--radius", str(radius_km)]
    if people:
        args += ["--people", *people] + (["--any-people"] if any_people else [])
    for flag, v in (("--since", date_from), ("--until", date_to), ("--text", text), ("--name", label)):
        if v:
            args += [flag, v]
    if not whole_days:
        args.append("--only-matching")
    args += ["--", *(folders or [])]  # paths after "--": never read as options
    st = await _run_job(args, "find", label or place or " ".join(people or []) or "find")
    return _finished(st)


@mcp.tool()
async def view_selection(selection: str, max_items: int = 24) -> list:
    """Show a saved selection again: summary, file list (first 60) and a contact sheet."""
    from . import catalog
    sel = catalog.load_selection(selection)
    sheet = await asyncio.to_thread(catalog.contact_sheet, sel["id"], max_items)
    files = [{k: f.get(k) for k in ("path", "kind", "created", "place", "people", "why")} for f in sel["files"][:60]]
    return _out({"summary": sel["summary"], "query": sel["query"], "files": files}, _img(sheet))


# ------------------------------------------------------------------ people
@mcp.tool()
async def people_list() -> str:
    """People TripShots can recognise (name, aliases, number of reference faces)."""
    from . import people
    return _txt({"people": people.list_people(), "models": people.available()[1]})


@mcp.tool()
async def people_add(name: str, photos: list[str], aliases: list[str] | None = None) -> str:
    """Teach TripShots a person from 2-5 photos where their face is the largest (selfies, portraits).
    Use name "me" for the user. Aliases: other names for them ("Abel", "mom" -> "Mary")."""
    from . import people
    return _txt(await asyncio.to_thread(people.enroll, name, photos, aliases))


@mcp.tool()
async def people_discover(folders: list[str] | None = None) -> list:
    """Group the faces nobody is named for yet into clusters (c1, c2, ...) and return a sheet of example faces.
    Show it to the user and ask who is who, then call people_name. First run reads every photo once (slow)."""
    st = await _run_job(["people", "discover", "--", *(folders or [])], "discover", "people")
    return _finished(st)


@mcp.tool()
async def people_name(cluster_id: str, name: str) -> str:
    """Name a discovered face cluster ("c2" -> "me", "mom", "Alex")."""
    from . import people
    return _txt(await asyncio.to_thread(people.name_cluster, cluster_id, name))


# ------------------------------------------------------------------ making reels
def _music_dirs() -> list[str]:
    v = os.environ.get("TRIPSHOTS_MUSIC", "")
    return [p for p in v.split(os.pathsep) if p.strip()]


@mcp.tool()
async def list_music() -> str:
    """Music the user has: audio files in their music folders and recently used tracks. A reel link
    (instagram.com/reel/...) also works as music in make_reel."""
    from .util import read_json
    exts = {".mp3", ".m4a", ".wav", ".aac", ".flac", ".ogg"}
    files = []
    for d in _music_dirs():
        for p in sorted(Path(d).expanduser().rglob("*")):
            if p.suffix.lower() in exts:
                files.append(str(p))
    recent = (read_json(HOME / "tui.json", {}) or {}).get("recent_music", [])
    return _txt({"music_files": files[:200], "recent": recent[:10], "folders": _music_dirs()})


@mcp.tool()
async def list_styles_and_looks() -> str:
    """Edit styles (pace, transitions, text) and colour looks to choose from."""
    from .config import load_style
    from .grade import list_looks
    styles = {}
    for n in sorted(list_styles()):
        try:
            styles[n] = load_style(n).get("description", "")
        except Exception:
            styles[n] = ""
    return _txt({"styles": styles, "looks": {k: v.get("desc", "") for k, v in list_looks().items()},
                 "text_presets": ["bold", "editorial", "minimal", "handwritten", "typewriter"]})


@mcp.tool()
async def make_reel(sources: list[str], music: str | None = None, style: str | None = None,
                    duration: float | None = None, hook: str | None = None, location: str | None = None,
                    look: str | None = None, text_preset: str | None = None, variants: int = 1,
                    route_map: str | None = None, dry_run: bool = True, name: str | None = None,
                    upload_copy: bool = False, speed_ramps: str | None = None, speed_up: str | None = None,
                    drop_speed: str | None = None, format: str | None = None,
                    text_motion: str | None = None, no_location: bool = False,
                    captions: str | None = None) -> list:
    """Plan (dry_run=true, default) or plan+render a reel.

    sources: selection ids from find_footage ("sel:xxxx") and/or folders/files.
    music: an audio file path or an Instagram reel link (its sound is used). None = silent at 100 BPM.
    style: from list_styles_and_looks (default: the app's default). duration: seconds (default: the style's).
    hook: opening text, 7 words max (default: the AI writes one). location: "Place, Region" label.
    captions: subtitles of the words in the music (film dialogue, song lines): auto (dialogue: English, songs: none),
      off, original (as said, in their own script), or a language name/code (english, malayalam, hindi, es...).
    no_location: true = no place names on screen at all (no title, none in the hook, no numbered place list).
    look: colour look or "auto". route_map: intro | tracker | both | off.
    speed_ramps: on | off | which ramps, e.g. "velocity,slam" (velocity, slam, bullet, rush, surge).
    speed_up: on | off (fast-forward moving clips in busy sections). drop_speed: rush | impact | both | off.
    text_motion: auto | off | rise | focus | tracking | typewriter | slam | write | cinema: how the words animate
      (HyperFrames; auto picks one per text preset when the runtime is installed).
    format: auto | montage | pov | list (numbered places) | series ("Day N of") | reveal. Every reel is planned as a
      story (hook, build, payoff, looping end) and checked by the critic; the result's "score" and "critic" file
      say what it fixed and what is still weak.
    upload_copy: also write a copy without the music (automatic for reel links), so the user can post it and add the
      same sound inside Instagram: do this when the music is a commercial song.
    Returns the plan path and the storyboard image to review (or a job id to poll)."""
    args = ["make"]
    for flag, v in (("-m", music), ("-s", style), ("-d", duration), ("--hook", hook), ("--location", location),
                    ("--look", look), ("--text-preset", text_preset), ("--route-map", route_map),
                    ("--speed-ramps", speed_ramps), ("--speed-up", speed_up), ("--drop-speed", drop_speed),
                    ("--format", format), ("--text-motion", text_motion), ("--captions", captions)):
        if v not in (None, ""):
            args += [flag, str(v)]
    if variants and variants > 1:
        args += ["--variants", str(variants)]
    if upload_copy:
        args.append("--upload-copy")
    if no_location:
        args.append("--no-location")
    if dry_run:
        args.append("--dry-run")
    if name:
        safe = re.sub(r"[^A-Za-z0-9 ._-]+", "-", name).strip(" .-")[:80] or "reel"
        out = Path(os.environ.get("TRIPSHOTS_OUT") or Path.cwd() / "reels") / f"{safe}.mp4"
        args += ["-o", str(out)]
    args += ["--", *sources]  # paths after "--": never read as options
    st = await _run_job(args, "make", name or " ".join(sources))
    return _finished(st)


@mcp.tool()
async def reel_results(reel: str | None = None, views: float | None = None, avg_watch: float | None = None,
                       sends: float | None = None, saves: float | None = None, likes: float | None = None,
                       comments: float | None = None) -> dict:
    """How the user's posted reels did, and what works for their audience. With `reel` (a reel's .mp4 or
    .plan.json) and numbers from Instagram Insights (views, avg_watch in seconds, sends = shares, saves...),
    records them first. Returns every recorded reel with its score (watch-through and sends per view) and the
    format / hook type that has done best so far; `make_reel` with format=auto leans on it once confident."""
    from . import results as R
    if reel and any(v is not None for v in (views, avg_watch, sends, saves, likes, comments)):
        await asyncio.to_thread(R.add, reel, {"views": views, "avg_watch": avg_watch, "sends": sends, "saves": saves,
                                              "likes": likes, "comments": comments})
    rows = R.load()
    return {"reels": [{"reel": r["reel"], "score": r.get("score"), "features": r.get("features"),
                       "metrics": r.get("metrics")} for r in rows][-30:], "preferences": R.preferences()}


@mcp.tool()
async def job_status(job_id: str, wait_seconds: float = 50) -> list:
    """Progress or result of a background job (waits up to wait_seconds for it to finish)."""
    st = await asyncio.to_thread(jobs.wait, job_id, min(max(wait_seconds, 0), 110))
    return _finished(st)


@mcp.tool()
async def cancel_job(job_id: str) -> str:
    """Stop a running job."""
    return _txt(jobs.cancel(job_id))


@mcp.tool()
async def show_plan(plan: str) -> list:
    """The current plan as a table (slot, time, shot, source file, transition, note) plus the storyboard image."""
    from .export import export
    p = _plan(plan)
    ex = await asyncio.to_thread(export, p, True, False, True, True)
    md = Path(ex["storyboard_md"]).read_text()
    sb = p.with_name(p.name.replace(".plan.json", ".storyboard.jpg"))
    return _out(md, _img(sb))


@mcp.tool()
async def shot_candidates(plan: str, top: int = 30) -> list:
    """The best shots from this plan's footage (ids, scores, AI notes; "used" = already in the reel) and a
    sheet of their thumbnails, for swapping weak slots with edit_plan."""
    from . import planedit
    c = await asyncio.to_thread(planedit.candidates, _plan(plan), top)
    sheet = await asyncio.to_thread(planedit.candidates_sheet, _plan(plan), top)
    return _out([{k: v for k, v in x.items() if k != "thumb"} for x in c], _img(sheet))


@mcp.tool()
async def edit_plan(plan: str, edits: list[dict]) -> list:
    """Change a planned reel without breaking the beat grid. Slots are numbered from 1 as on the storyboard.
    edits, applied in order:
      {"op":"swap","segment":3,"shot_id":"S012"}  {"op":"move","from":5,"to":1}  {"op":"exchange","a":2,"b":6}
      {"op":"text","type":"hook"|"location"|"cta","text":"..."}  {"op":"remove_text","type":"location"}
      {"op":"transition","segment":2,"to":"whip"|"zoom_in"|"zoom_out"|"spin"|"flash"|"glitch"|"blur"|"dissolve"|"dip"|"leak"|null}
      {"op":"speed","segment":4,"speed":0.5}  (0.5 slow motion, 2 = twice as fast)
      {"op":"ramp","segment":4,"ramp":"velocity"|"slam"|"bullet"|"rush"|"impact"|"surge"|null,"hit":0.6}
        (hit = seconds into the slot where it slams into slow motion; "points":[[0,1],[0.4,0.3],[1,1]] for a custom curve)
      {"op":"frame","segment":4,"subject_x":0.3}
      {"op":"set","path":"motion.beat_punch","value":0.04}
    Returns the new storyboard. Then render_reel."""
    from . import planedit
    res = await asyncio.to_thread(planedit.apply, _plan(plan), edits)
    return _out(res, _img(res.get("storyboard")))


@mcp.tool()
async def render_reel(plan: str, encoder: str | None = None) -> list:
    """Render a (reviewed) plan to the final mp4: video, cover, caption, sound design. Takes a few minutes:
    returns a job id; poll job_status."""
    args = ["render", str(_plan(plan))] + (["--encoder", encoder] if encoder else [])
    st = await _run_job(args, "render", Path(plan).name, wait=20)
    return _finished(st)


@mcp.tool()
async def check_reel(video: str) -> list:
    """Quality checks on a rendered reel (they also run after every render): size/fps/codecs, length, loudness
    (-14 LUFS, true peak), black / frozen / silent stretches, text inside Instagram's safe area, text big enough
    and on screen long enough to read. Returns the report and a contact sheet of 12 frames to look at."""
    from .qa import check
    v = Path(video).expanduser()
    if v.suffix.lower() not in (".mp4", ".mov") or not v.is_file():
        return [_txt(f"not a rendered reel: {video}")]
    rep = await asyncio.to_thread(check, v)
    out = [_txt(rep)]
    if rep.get("sheet") and Path(rep["sheet"]).exists():
        out.append(_img(Path(rep["sheet"])))
    return out


@mcp.tool()
async def export_edit(plan: str) -> str:
    """Hand the edit to DaVinci Resolve / Premiere / Final Cut: writes .edl, .otio and .storyboard.md."""
    from .export import export
    return _txt(await asyncio.to_thread(export, _plan(plan)))


@mcp.tool()
async def analyze_footage(sources: list[str] | None = None, ai: bool = True, faces: bool = True, places: bool = True,
                          cached: bool = False) -> list:
    """Analyse photos and videos on their own, without making a reel: for every file its capture time, place, camera,
    trip and people, and for every shot (a photo, or a scene of a video) technical quality (sharpness, exposure,
    colours, near-duplicates, camera motion) and an AI description (caption, description, tags, subjects with boxes,
    scene, time of day, weather, people, visible text, landmark, aesthetic 1-10, issues). Writes media.jsonl
    (schema tripshots.media/1) that reels, collage apps and other tools reuse. Incremental: only new files cost time.
    sources: folders, files or sel:<id> (default: the footage folders). cached: export only what's already analysed."""
    args = ["analyze"] + (["--no-ai"] if not ai else []) + (["--no-faces"] if not faces else []) + \
        (["--no-places"] if not places else []) + (["--cached"] if cached else []) + ["--", *(sources or [])]
    st = await _run_job(args, "analyze", " ".join(sources or ["footage"]))
    return _finished(st)


@mcp.tool()
async def search_media(text: str | None = None, tags: list[str] | None = None, people: list[str] | None = None,
                       kind: str | None = None, min_aesthetic: float | None = None, sharp_only: bool = False,
                       scene: str | None = None, day: str | None = None, analysis: str | None = None,
                       full: bool = False, limit: int = 30) -> str:
    """Search an analysis (default: the latest) for photos/shots: text matches captions, descriptions, tags, places
    and landmarks; tags/people must all be present; min_aesthetic 1-10; scene e.g. "food", "mountains"; day
    YYYY-MM-DD. Returns compact records (full=true for the whole tripshots.media/1 record)."""
    from . import analysis as an
    recs = await asyncio.to_thread(an.query, analysis, text, tags, people, kind, min_aesthetic, sharp_only, scene,
                                   day, max(1, min(limit, 200)))
    return _txt({"count": len(recs), "records": recs if full else [an.compact(r) for r in recs]})


@mcp.tool()
async def edits_package(plan: str, clips: bool = True) -> list:
    """Prepare a planned reel for Instagram's Edits app (Mac): renders the picture with everything only TripShots
    can do baked in (grade, motion, transitions, split screens, maps, titles behind the skyline), and writes the
    rest separately so it stays editable in Edits: one clip per shot, the texts (with timings, plus PNGs of
    TripShots' styling), the sound effects track, the song and a manifest.json. Takes a few minutes: returns a job.

    Then either call edits_push, or, if the Edits MCP tools are connected to you as well, assemble it there from
    manifest.json: new 9:16 project; clips at their starts (or picture.mp4 at 0); each text as Edits text at its
    start/duration; sound-effects.wav at 0; the song from Edits' library at music.song_start. Use paths under
    'staged' when present (Edits can only open files in its own container). Don't export or post unless asked."""
    args = ["edits", "package", str(_plan(plan))] + ([] if clips else ["--no-clips"])
    st = await _run_job(args, "edits", Path(plan).name, wait=20)
    return _finished(st)


@mcp.tool()
async def edits_status() -> str:
    """Is Edits reachable, which automation tools does it offer, and is TripShots' mapping to them confirmed?"""
    from . import edits
    from .util import read_json
    out = {"url": edits._url(), "token_set": bool(os.environ.get("TRIPSHOTS_EDITS_TOKEN"))}
    try:
        out.update(await asyncio.to_thread(edits.tools))
    except ReelError as e:
        out["error"] = str(e)
    prof = read_json(edits.PROFILE)
    out["mapping"] = ({"confirmed": prof.get("confirmed"), "steps": {k: v["tool"] for k, v in prof["steps"].items()}}
                      if prof else "none yet: run `tripshots edits probe`")
    return _txt(out)


@mcp.tool()
async def edits_push(package: str, picture: bool = False, music: str = "library", text_as: str = "text") -> str:
    """Build the timeline in Edits from an edits_package folder, through the user's confirmed tool mapping.
    picture: one video clip instead of one per shot. music: library (leave the song to add from Edits' library,
    the default), file (add music.m4a) or none. text_as: text (editable Edits text) or image (TripShots' PNGs)."""
    from . import edits
    p = Path(package).expanduser()
    if not (p / "manifest.json").is_file():
        raise ReelError(f"not an Edits package: {package}")
    return _txt(await asyncio.to_thread(edits.push, p, "picture" if picture else "clips", music, text_as))


@mcp.prompt()
def reel_from_request(request: str) -> str:
    """Make a reel from a plain-language request ("a reel about my days in Yellowstone")."""
    return f"{INSTRUCTIONS}\n\nThe user's request: {request}"


# ------------------------------------------------------------------ run
def _default_out():
    if not os.environ.get("TRIPSHOTS_OUT"):
        from .util import is_mac, read_json
        st = read_json(HOME / "tui.json", {}) or {}
        os.environ["TRIPSHOTS_OUT"] = st.get("out_dir") or str(
            (Path.home() / "Movies" / "Reels") if is_mac() else (Path.home() / "reels"))


def main(http: str | None = None) -> None:
    load_env()
    _default_out()
    if not http:
        mcp.run("stdio")
        return
    host, _, port = http.rpartition(":")
    host = host or "127.0.0.1"
    token = os.environ.get("TRIPSHOTS_MCP_TOKEN")
    if host not in ("127.0.0.1", "localhost", "::1") and not token:
        raise ReelError("set TRIPSHOTS_MCP_TOKEN before serving beyond this computer "
                        "(clients send it as 'Authorization: Bearer <token>')")
    import uvicorn
    try:
        app = mcp.streamable_http_app(host=host)
    except TypeError:  # mcp 1.x
        app = mcp.streamable_http_app()
    if token:
        app = _BearerAuth(app, token)
    print(f"TripShots MCP on http://{host}:{port}/mcp" + (" (bearer token required)" if token else ""),
          file=sys.stderr)
    uvicorn.run(app, host=host, port=int(port), log_level="warning")


class _BearerAuth:
    """Minimal ASGI guard: every HTTP request needs the shared token."""

    def __init__(self, app, token: str):
        self.app, self.token = app, token.encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            import hmac
            auth = dict(scope.get("headers") or []).get(b"authorization", b"")
            if not hmac.compare_digest(auth, b"Bearer " + self.token):
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"text/plain"), (b"www-authenticate", b"Bearer")]})
                await send({"type": "http.response.body", "body": b"unauthorized"})
                return
        await self.app(scope, receive, send)
