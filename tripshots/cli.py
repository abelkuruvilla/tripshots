"""tripshots command line.

  tripshots make  ~/SSD/Trips/Banff --music song.mp3 --style beat-montage
  tripshots learn https://www.instagram.com/reel/XXXX/ --name my-style
  tripshots render reels/Banff-...plan.json
  tripshots look https://www.instagram.com/reel/XXXX/ --name dreamy
  tripshots grade ~/SSD/Trips/Banff/photos --look dreamy
  tripshots styles
  tripshots doctor
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import util
from .config import HOME, list_styles, load_env, load_style


def source_opts(a) -> dict:
    return {"exclude": a.exclude, "recursive": not a.no_recursive, "live_photos": a.include_live_photos,
            "since": a.since, "until": a.until, "watch": getattr(a, "watch", None)}


def inputs_of(a) -> list[Path]:
    """Folders, files and `sel:<id>` selections from `tripshots find`."""
    from .catalog import expand_inputs
    paths, label = expand_inputs(a.inputs)
    a._label = label
    return paths


def cmd_make(a):
    from .pipeline import make_variants
    res = make_variants(a.variants, inputs_of(a), a.music, a.style,
               Path(a.out) if a.out else None, a.duration, a.backend, a.hook, a.location, a.no_location,
               a.dry_run, workers=a.workers, source_opts=source_opts(a), cookies=cookie_args(a),
               music_start=a.music_start, upload_copy=a.upload_copy, min_score=a.min_score,
               allow_similar=a.allow_similar, rescore=a.rescore, text_preset=a.text_preset, behind=a.behind,
               extras={"split": a.split_screens, "ramps": a.speed_ramps, "labels": a.labels, "loop": a.loop,
                       "name": a._label},
               look=a.look, grade_strength=a.grade_strength, route_map=a.route_map, sound=sound_args(a))
    print(json.dumps(res, indent=2))


def cmd_clone(a):
    from .pipeline import clone
    res = clone(a.reference, inputs_of(a), Path(a.out) if a.out else None, a.style, a.backend,
                variants=a.variants, look=a.look, grade_strength=a.grade_strength, cookies=cookie_args(a),
                keep_text=a.keep_text, dry_run=a.dry_run, workers=a.workers, source_opts=source_opts(a),
                upload_copy=a.upload_copy, rescore=a.rescore, text_preset=a.text_preset, hype=a.hype,
                sound=sound_args(a))
    print(json.dumps(res, indent=2))


def cmd_render(a):
    from .pipeline import render_plan
    out = render_plan(Path(a.plan), Path(a.out) if a.out else None, workers=a.workers)
    res = {"video": str(out), "plan": str(Path(a.plan).resolve())}
    for key, ext in (("cover", ".cover.jpg"), ("storyboard", ".storyboard.jpg"), ("caption", ".caption.txt"),
                     ("grade", ".grade.jpg"), ("upload_video", ".noaudio.mp4"), ("upload_video", ".nomusic.mp4")):
        f = out.with_name(out.stem + ext)
        if f.exists():
            res[key] = str(f)
    print(json.dumps(res, indent=2))


def sound_args(a) -> dict:
    return {"sfx": a.sfx, "ambience": a.ambience, "native": getattr(a, "clip_sound", None), "level_db": a.sfx_level,
            "licenses": a.sfx_licenses}


def add_encoder_arg(sp):
    sp.add_argument("--encoder", choices=["auto", "hardware", "software", "videotoolbox", "nvenc", "qsv"],
                    help="video encoder: auto (default: the Mac's / GPU's hardware encoder when it works, "
                         "else libx264), hardware, software (libx264, slowest, smallest files), or a specific one")


def add_sound_args(sp):
    g = sp.add_argument_group("sound design (real sound effects on the cuts, ambience per place)")
    g.add_argument("--sfx", choices=["on", "off"], help="sound effects on transitions, the drop, text pops (default: style)")
    g.add_argument("--ambience", choices=["on", "off"], help="quiet waves / wind / birds / city bed per place")
    g.add_argument("--clip-sound", choices=["auto", "on", "off"],
                   help="use a clip's own sound (real waves, real street) as its ambience when it is clean (default auto)")
    g.add_argument("--sfx-level", type=float, metavar="DB", help="effects louder (+3) or quieter (-3)")
    g.add_argument("--sfx-licenses", metavar="LIST",
                   help="Openverse licences to use: cc0,pdm (default, no credit needed) or cc0,pdm,by (credited)")


def cmd_sounds(a):
    from . import sound
    lic = a.licenses or sound.LICENSES_DEFAULT
    if a.fetch:
        util.log(f"fetching real sound effects from Openverse ({lic}), once; cached in {sound.SFX_HOME}")
        sound.prefetch(lic, ambience=not a.no_ambience)
    print(json.dumps(sound.status(lic), indent=2))


def cmd_listen(a):
    from . import sound
    print(json.dumps(sound.listen(Path(a.video)), indent=2))


def cookie_args(a) -> dict:
    return {"cookies_browser": getattr(a, "cookies_from_browser", None), "cookies_file": getattr(a, "cookies", None)}


def cmd_learn(a):
    from .learn import learn
    print(learn(a.refs, a.name, a.backend, a.cookies_from_browser, a.cookies))


def cmd_music(a):
    from .fetch import audio_meta, fetch_audio
    from .music import analyze_music
    from .config import HOME
    path = fetch_audio(a.url, a.cookies_from_browser, a.cookies, Path(a.out) if a.out else None, a.refresh)
    meta = audio_meta(path) if not a.out else {}
    info = analyze_music(path, HOME / "music")
    print(json.dumps({"audio": str(path), "label": meta.get("label"), "duration": round(info["duration"], 1),
                      "tempo_bpm": round(info["tempo"]), "beats": len(info["beats"])}, indent=2))


def cmd_scan(a):
    from .pipeline import prepare_shots
    shots, _, work = prepare_shots(inputs_of(a), a.backend, source_opts=source_opts(a),
                                   rescore=a.rescore)
    shots.sort(key=lambda s: s["ai"]["score"], reverse=True)
    for s in shots[: a.top]:
        ai = s["ai"]
        span = "photo" if s["kind"] == "photo" else f"{s['t0']:.1f}-{s['t1']:.1f}s"
        print(f"{s['id']}  {ai['score']:>4}  {s['name']:<28} {span:<12} {','.join(ai.get('tags', [])):<24} {ai.get('note', '')}")
    print(f"\nscored shots: {work / 'shots_scored.json'}")


def cmd_frame(a):
    from .media import PHOTO_EXT, find_media
    from .popout import make_still
    out_dir = Path(a.out).expanduser() if a.out else Path.cwd() / "frames"
    files = [p for p in find_media([Path(x) for x in a.inputs]) if p.suffix.lower() in PHOTO_EXT]
    if not files:
        raise util.ReelError("no photos found")
    made, skipped = [], []
    for i, p in enumerate(files, 1):
        util.log(f"framing {i}/{len(files)}: {p.name}")
        try:
            for fmt in (["post", "story"] if a.format == "both" else [a.format]):
                made.append(str(make_still(p, out_dir / f"{p.stem}-{fmt}.jpg", fmt, a.bg, a.variant,
                                           border=18 if a.border else 0, look=a.look)))
        except util.ReelError as e:
            util.log(f"  skipped: {e}")
            skipped.append(p.name)
    print(json.dumps({"frames": made, "folder": str(out_dir), "skipped": skipped}, indent=2))


def cmd_look(a):
    from .ai import get_backend
    from . import grade
    p = grade.look_from_refs(a.refs, a.name, get_backend(a.backend), a.cookies_from_browser, a.cookies)
    lk = grade.get_look(a.name)
    print(json.dumps({"look": a.name, "description": lk.get("desc"), "file": str(p),
                      "reference_frames": str(grade.HOME / "learn" / f"look-{a.name}" / "reference.jpg"),
                      "use_it": f"tripshots make <folders> --look {a.name}   or   tripshots grade <photos> --look {a.name}"},
                     indent=2))


def cmd_looks(a):
    from . import grade
    for name, lk in grade.list_looks().items():
        print(f"{name:<14} {'' if lk.get('builtin') else '(yours) '}{lk.get('desc', '')}")


def cmd_grade(a):
    from . import grade
    from .ai import get_backend  # noqa: F401  (AI notes are used inside reels; files use measurements)
    out_dir = Path(a.out).expanduser() if a.out else Path.cwd() / "graded"
    try:
        outs = grade.grade_files([Path(x) for x in a.inputs], a.look, a.strength, out_dir)
    except KeyError as e:
        raise util.ReelError(str(e).strip("'\""))
    if not outs:
        raise util.ReelError("no photos or videos found")
    print(json.dumps({"graded": [str(o) for o in outs if "before-after" not in o.name],
                      "before_after": next((str(o) for o in outs if "before-after" in o.name), None),
                      "folder": str(out_dir)}, indent=2))


def cmd_maps(a):
    from . import routemap
    if a.setup:
        routemap.ensure_runtime()
        routemap.topo()
    st = routemap.runtime_status()
    print(json.dumps({**st, "ready": bool(st["node"] and st["installed"]),
                      "fix": None if st["node"] else "brew install node   (then: tripshots maps --setup)"}, indent=2))


def cmd_library(a):
    from . import library as lib
    if a.forget_ai:
        print(f"forgot {lib.forget_scores()} AI verdicts (footage analysis kept)")
        return
    if a.wipe:
        import shutil
        shutil.rmtree(lib.LIB_DIR, ignore_errors=True)
        print(f"deleted {lib.LIB_DIR}")
        return
    print(json.dumps(lib.stats(), indent=2))


def cmd_styles(a):
    for name, p in list_styles().items():
        st = load_style(str(p))
        print(f"{name:<16} {st.get('description', '')}")


def cmd_export(a):
    from .export import export
    every = not (a.edl or a.otio or a.md)
    print(json.dumps(export(Path(a.plan), edl=a.edl or every, otio=a.otio or every, md=a.md or every), indent=2))


def cmd_find(a):
    from . import catalog
    near = [float(x) for x in a.near.split(",")] if a.near else None
    res = catalog.find(a.folders or None, place=a.place, near=near, radius_km=a.radius, people=a.people,
                       people_mode="any" if a.any_people else "all", date_from=a.since, date_to=a.until,
                       kinds=a.kind, whole_days=not a.only_matching, text=a.text, label=a.name)
    if a.sheet and res["count"]:
        res["sheet"] = str(catalog.contact_sheet(res["selection"]))
    if a.list:
        res["files"] = [f["path"] for f in catalog.load_selection(res["selection"])["files"]]
    print(json.dumps(res, indent=2))


def cmd_trips(a):
    from . import catalog
    print(json.dumps({"trips": catalog.trips(a.folders or None, name=not a.no_names)}, indent=2))


def cmd_footage(a):
    from . import catalog
    if a.folders:
        catalog.set_footage_roots(a.folders)
    print(json.dumps({"footage": [str(p) for p in catalog.footage_roots()]}, indent=2))


def cmd_people(a):
    from . import catalog, people
    if a.action == "list":
        res = {"people": people.list_people()}
    elif a.action == "add":
        if not a.args or len(a.args) < 2:
            raise util.ReelError("usage: tripshots people add <name> <photo> [photo...]")
        res = people.enroll(a.args[0], a.args[1:])
    elif a.action == "discover":
        res = people.discover(catalog.records(a.args or None))
    elif a.action == "name":
        if not a.args or len(a.args) != 2:
            raise util.ReelError("usage: tripshots people name <cluster id> <name>")
        res = people.name_cluster(a.args[0], a.args[1])
    elif a.action == "forget":
        res = {"forgot": people.forget(a.args[0]) if a.args else False}
    else:  # who: who is in these files
        recs = catalog.records(a.args or None)
        res = {r["path"]: n for r, n in ((r, people.who_is_in([r])[r["path"]]) for r in recs) if n}
    print(json.dumps(res, indent=2))


def cmd_edits(a):
    from . import edits
    if a.action == "package":
        if not a.target:
            raise util.ReelError("usage: tripshots edits package <NAME.plan.json>")
        res = edits.package(Path(a.target), Path(a.out) if a.out else None, clips=not a.no_clips, stage=a.stage,
                            workers=a.workers)
    elif a.action == "tools":
        res = edits.tools(a.url, a.token)
    elif a.action == "probe":
        res = edits.probe(a.url, a.token)
    else:
        if not a.target:
            raise util.ReelError("usage: tripshots edits push <NAME.edits>")
        res = edits.push(Path(a.target), mode="picture" if a.picture else "clips", music=a.music,
                         text_as=a.text_as, url=a.url, token=a.token)
    print(json.dumps(res, indent=2))


def cmd_analyze(a):
    from . import analysis
    paths = inputs_of(a) if a.inputs else []
    if not paths:
        from .catalog import footage_roots
        paths = footage_roots()
        if not paths:
            raise util.ReelError("nothing to analyse: pass folders/files/sel:<id>, or set footage folders "
                                 "(`tripshots footage <folders>`)")
    res = analysis.analyze(paths, a.backend, ai=not a.no_ai, faces=not a.no_faces, places=not a.no_places,
                           watch_mode=a.watch, rescore=a.rescore, cached=a.cached,
                           out_dir=Path(a.out) if a.out else None, label=getattr(a, "_label", None),
                           source_opts=source_opts(a))
    if a.print:
        res["records"] = list(analysis.load(res["output"]))
    print(json.dumps(res, indent=2, default=str))


def cmd_ask(a):
    from .ask import ask
    print(json.dumps(ask(" ".join(a.request), a.backend, a.music, render=a.render, workers=a.workers,
                         find_only=a.find_only), indent=2))


def cmd_doctor(a):
    from .ai import get_backend
    ok = True
    for tool in ("ffmpeg", "ffprobe"):
        found = util.which(tool)
        print(f"{tool:<10} {'ok  ' + found if found else 'MISSING'}")
        ok &= bool(found)
    for f in ("xfade", "lut3d"):
        print(f"filter {f:<8} {'ok' if util.has_filter(f) else 'missing (optional)'}")
    hdr = ("zscale + tonemap" if util.has_filter("zscale") and util.has_filter("tonemap")
           else "built-in tables (lut3d; same result)" if util.has_filter("lut3d") else "MISSING: HDR clips will look flat")
    print(f"{'HDR':<10} {hdr}")
    cl = util.which("claude")
    if cl:
        from .ai import ClaudeCLI
        st = ClaudeCLI.login_status()
        login = ("logged in" + (f" ({st.get('authMethod')})" if st.get("authMethod") else "") if st and st.get("loggedIn")
                 else "NOT logged in: run `claude auth login`" if st else "login status unknown (old Claude Code?)")
        print(f"{'claude':<10} {cl}  {login}")
    else:
        print(f"{'claude':<10} not found (needed for claude-cli backend)")
    try:
        import yt_dlp
        print(f"{'yt-dlp':<10} ok {yt_dlp.version.__version__} (update: re-run ./install.sh if reel links stop working)")
    except ImportError:
        print(f"{'yt-dlp':<10} not installed (needed for reel links: music + learn)")
    from .popout import have_cutout
    print(f"{'cut-out':<10} {'ok (rembg)' if have_cutout() else 'missing: pop-out frames need rembg (./install.sh)'}")
    from . import encode
    print(f"{'encoder':<10} {encode.describe()}")
    from . import catalog, people as ppl
    roots = catalog.footage_roots()
    print(f"{'footage':<10} {', '.join(map(str, roots)) if roots else 'not set (tripshots footage <folders>)'}")
    known = [p['name'] for p in ppl.list_people()]
    print(f"{'people':<10} {', '.join(known) if known else 'nobody yet (tripshots people add me <photos>)'}; "
          f"{ppl.available()[1]}")
    try:
        import mcp  # noqa: F401
        print(f"{'mcp':<10} ok (tripshots mcp)")
    except ImportError:
        print(f"{'mcp':<10} missing: pip install mcp (needed for AI agents)")
    from . import watch as w
    gem_ok, why = w.available()
    print(f"{'watch':<10} {'Gemini ' + w.DEFAULT_MODEL if gem_ok else 'local motion only: ' + why}")
    from . import sound as snd
    st = snd.status()
    real = sum(1 for r in st["roles"].values() if r["library"] or r["openverse"])
    print(f"{'sound fx':<10} {real}/{len(st['roles'])} roles with real recordings"
          + ("" if real else " (run `tripshots sounds --fetch`)") + (", earshot bank ok" if st["earshot"] else ""))
    from .routemap import runtime_status
    rs = runtime_status()
    print(f"{'route map':<10} " + ("ok (HyperFrames)" if rs["node"] and rs["installed"] else
                                   "optional: `tripshots maps --setup`" if rs["node"] else
                                   "optional: needs Node.js 22+ (`brew install node`)"))
    from .media import HEIF_OK
    print(f"{'HEIC':<10} {'ok (pillow-heif)' if HEIF_OK else ('macOS sips fallback' if util.is_mac() else 'pip install pillow-heif')}")
    try:
        b = get_backend(None)
        order = " -> ".join(x.name for x in getattr(b, "backends", [b])) if b else "none (heuristics only)"
        print(f"{'backend':<10} {order}" + ("  (the next takes over if one stops working)" if " -> " in order else ""))
    except Exception as e:
        print(f"{'backend':<10} error: {e}")
    print(f"{'home':<10} {HOME}")
    sys.exit(0 if ok else 1)


def main(argv=None):
    load_env()
    if argv is None and len(sys.argv) == 1:  # plain `tripshots`: open the app
        from .tui import run
        return run()
    p = build_parser()
    a = p.parse_args(argv)
    _run(p, a)


def build_parser() -> argparse.ArgumentParser:
    """The whole command line (also used to generate docs/cli.md)."""
    p = argparse.ArgumentParser(prog="tripshots", description="TripShots: turn travel footage into beat-synced Instagram Reels.",
                                fromfile_prefix_chars="@")

    def add_cookie_args(sp):
        g = sp.add_argument_group("instagram login (most reels need it)")
        g.add_argument("--cookies-from-browser", metavar="BROWSER",
                       help="chrome | safari | firefox | brave | edge (use the browser where you're logged in "
                            "to Instagram; 'chrome:Profile 1' for another profile). Default: $TRIPSHOTS_COOKIES_BROWSER")
        g.add_argument("--cookies", metavar="FILE", help="cookies.txt exported from your browser (alternative)")

    def add_source_args(sp):
        g = sp.add_argument_group("sources (folders are searched recursively, any number of them)")
        g.add_argument("--exclude", action="append", default=[], metavar="GLOB",
                       help="skip matching files/paths, e.g. --exclude '*/timelapse/*' --exclude 'DJI_*.JPG' (repeatable)")
        g.add_argument("--since", metavar="YYYY-MM-DD", help="only media captured on/after this date")
        g.add_argument("--until", metavar="YYYY-MM-DD", help="only media captured on/before this date")
        g.add_argument("--no-recursive", action="store_true", help="don't look inside subfolders")
        g.add_argument("--include-live-photos", action="store_true",
                       help="also use iPhone Live Photo motion clips (skipped by default)")
        g.add_argument("--watch", choices=["auto", "gemini", "off"],
                       help="Gemini watches each clip (480p proxy, cached): best instant, shake, tilt, whip pans. "
                            "auto = when GEMINI_API_KEY is set (default)")
        g.add_argument("--rescore", action="store_true",
                       help="ask the AI again about these shots instead of reusing its stored verdicts")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("make", help="build a reel from folders/files of photos and clips")
    m.add_argument("inputs", nargs="+", help="folders and/or files, sel:<id> from `tripshots find`, "
                                                 "or @list.txt with one path per line")
    m.add_argument("-m", "--music", help="audio file to cut to (mp3/m4a/wav), or an Instagram reel link to use its sound")
    m.add_argument("--text-preset", choices=["bold", "editorial", "minimal", "handwritten", "typewriter"],
                   help="text look (overrides the style)")
    m.add_argument("--behind", choices=["auto", "on", "off"], help="location title behind the skyline")
    m.add_argument("--split-screens", choices=["lots", "some", "off"], help="split-screen / grid moments")
    m.add_argument("--speed-ramps", choices=["on", "off"], help="velocity speed ramps on moving clips")
    m.add_argument("--labels", choices=["ai", "off"], help="a short AI label on each shot")
    m.add_argument("--loop", action=argparse.BooleanOptionalAction, default=None, help="seamless loop ending")
    m.add_argument("--min-score", type=float, metavar="N",
                   help="lowest AI score (1-10) a shot may have to be used (default: style's min_score - 2)")
    m.add_argument("--look", help="colour grade: auto (AI picks), none, a preset (see `tripshots looks`) "
                                  "or a look you made with `tripshots look`")
    m.add_argument("--grade-strength", type=float, metavar="0-1", help="how strongly the look is applied (default 0.75)")
    m.add_argument("--variants", type=int, default=1, metavar="N",
                   help="make N versions (different opening shot, order, transitions and hook) + a comparison "
                        "sheet, e.g. to test with Instagram trial reels")
    m.add_argument("--route-map", choices=["intro", "tracker", "both", "off"],
                   help="animated travel-route map from your GPS: intro = big card early on, tracker = small "
                        "corner map following each shot (needs Node.js; first use installs HyperFrames)")
    m.add_argument("--allow-similar", action="store_true",
                   help="also use shots the AI flagged as near-duplicates (bursts, same view)")
    m.add_argument("--music-start", type=float, metavar="SEC",
                   help="start the song here (default: best part of a file; 0:00 for a reel link)")
    m.add_argument("--upload-copy", action=argparse.BooleanOptionalAction, default=None,
                   help="also write an upload copy without the music (NAME.nomusic.mp4, which keeps the sound effects; NAME.noaudio.mp4 without sound design), then add the sound in Instagram "
                        "(default: on when --music is a link)")
    add_cookie_args(m)
    add_sound_args(m)
    m.add_argument("-s", "--style", default="beat-montage", help="style name or path to YAML")
    m.add_argument("-d", "--duration", type=float, help="target length in seconds")
    m.add_argument("-o", "--out", help="output .mp4 path")
    m.add_argument("-b", "--backend", help="claude-cli | api | minimax | none (default: auto)")
    m.add_argument("--hook", help="on-screen hook text (overrides style/AI)")
    m.add_argument("--location", help="location label text (overrides GPS lookup)")
    m.add_argument("--no-location", action="store_true", help="no location label")
    m.add_argument("--dry-run", action="store_true", help="write plan + storyboard only")
    m.add_argument("-j", "--workers", type=int, default=2)
    add_source_args(m)
    add_encoder_arg(m)
    m.set_defaults(fn=cmd_make)

    cl = sub.add_parser("clone", help="remake a reel you like shot for shot with your own footage")
    cl.add_argument("reference", help="Instagram reel link (or a saved video) to copy")
    cl.add_argument("inputs", nargs="+", help="your footage folders/files")
    cl.add_argument("--variants", type=int, default=1, metavar="N", help="N versions using the runner-up shots/text")
    cl.add_argument("--look", help="colour: default copies the reference's grade; or auto/none/a look name")
    cl.add_argument("--grade-strength", type=float, metavar="0-1")
    cl.add_argument("--keep-text", action="store_true", help="copy the reference's text word for word")
    cl.add_argument("--hype", action="store_true", help="add the style's freeze-frame / colour-split effects")
    cl.add_argument("--text-preset", choices=["bold", "editorial", "minimal", "handwritten", "typewriter"])
    cl.add_argument("--upload-copy", action=argparse.BooleanOptionalAction, default=None,
                    help="also write an upload copy without the music (default: on for links)")
    cl.add_argument("-s", "--style", help="style for motion/text look (default beat-montage)")
    cl.add_argument("-o", "--out")
    cl.add_argument("-b", "--backend")
    cl.add_argument("--dry-run", action="store_true")
    cl.add_argument("-j", "--workers", type=int, default=2)
    add_cookie_args(cl)
    add_sound_args(cl)
    add_source_args(cl)
    add_encoder_arg(cl)
    cl.set_defaults(fn=cmd_clone)

    r = sub.add_parser("render", help="re-render an (edited) plan.json")
    r.add_argument("plan")
    r.add_argument("-o", "--out")
    r.add_argument("-j", "--workers", type=int, default=2)
    add_encoder_arg(r)
    r.set_defaults(fn=cmd_render)

    ex = sub.add_parser("export", help="hand the edit to Resolve / Premiere / Final Cut: EDL, OTIO, storyboard.md")
    ex.add_argument("plan")
    ex.add_argument("--edl", action="store_true", help="CMX3600 .edl")
    ex.add_argument("--otio", action="store_true", help="OpenTimelineIO .otio (needs opentimelineio)")
    ex.add_argument("--md", action="store_true", help="readable .storyboard.md")
    ex.set_defaults(fn=cmd_export)

    lr = sub.add_parser("learn", help="learn a style from reference reels (URLs or files)")
    lr.add_argument("refs", nargs="+")
    lr.add_argument("-n", "--name", required=True)
    lr.add_argument("-b", "--backend")
    add_cookie_args(lr)
    lr.set_defaults(fn=cmd_learn)

    mu = sub.add_parser("music", help="download the sound of an Instagram reel (or any yt-dlp link)")
    mu.add_argument("url")
    mu.add_argument("-o", "--out", help="copy the audio to this file or folder")
    mu.add_argument("--refresh", action="store_true", help="download again even if cached")
    add_cookie_args(mu)
    mu.set_defaults(fn=cmd_music)

    sc = sub.add_parser("scan", help="analyze + score footage and list the best shots")
    sc.add_argument("inputs", nargs="+")
    sc.add_argument("-b", "--backend")
    sc.add_argument("--top", type=int, default=30)
    add_source_args(sc)
    sc.set_defaults(fn=cmd_scan)

    fr = sub.add_parser("frame", help="pop-out frame stills: the subject steps out of a framed photo")
    fr.add_argument("inputs", nargs="+", help="photos and/or folders")
    fr.add_argument("-f", "--format", choices=["post", "story", "square", "both"], default="post",
                    help="post = 4:5 feed/carousel, story = 9:16")
    fr.add_argument("--bg", choices=["paper", "blur", "solid", "dark"], default="paper")
    fr.add_argument("--variant", choices=["auto", "top", "bottom"], default="auto",
                    help="top = head breaks out above the frame, bottom = legs/ground spill below")
    fr.add_argument("--border", action="store_true", help="white print border around the photo")
    fr.add_argument("--look", help="colour grade the photo: auto, a preset or your look (see `tripshots looks`)")
    fr.add_argument("-o", "--out", help="output folder (default ./frames)")
    fr.set_defaults(fn=cmd_frame)

    lk = sub.add_parser("look", help="copy the colour grade of reels/videos/photos you like into a reusable look")
    lk.add_argument("refs", nargs="+", help="Instagram reel links, videos, photos or folders")
    lk.add_argument("-n", "--name", required=True)
    lk.add_argument("-b", "--backend")
    add_cookie_args(lk)
    lk.set_defaults(fn=cmd_look)

    sub.add_parser("looks", help="list colour looks (built-in and yours)").set_defaults(fn=cmd_looks)

    gr = sub.add_parser("grade", help="colour grade photos and videos (graded copies + before/after sheet)")
    gr.add_argument("inputs", nargs="+", help="photos, videos and/or folders")
    gr.add_argument("-l", "--look", default="auto", help="auto, a preset or your look (see `tripshots looks`)")
    gr.add_argument("--strength", type=float, default=0.8, help="0-1 (default 0.8)")
    gr.add_argument("-o", "--out", help="output folder (default ./graded)")
    gr.set_defaults(fn=cmd_grade)

    so = sub.add_parser("sounds", help="sound effects: what's available per role, or --fetch real ones from Openverse")
    so.add_argument("--fetch", action="store_true", help="download a starter set of CC0 effects + ambiences (once)")
    so.add_argument("--licenses", help="cc0,pdm (default) or cc0,pdm,by")
    so.add_argument("--no-ambience", action="store_true")
    so.set_defaults(fn=cmd_sounds)

    li = sub.add_parser("listen", help="earshot listens to a finished reel: events, sync, loudness (optional models)")
    li.add_argument("video")
    li.set_defaults(fn=cmd_listen)

    mp = sub.add_parser("maps", help="route-map layer (HyperFrames): status, or --setup to install it")
    mp.add_argument("--setup", action="store_true", help="install the Node packages (one time, ~100 MB)")
    mp.set_defaults(fn=cmd_maps)

    lb = sub.add_parser("library", help="what TripShots remembers about your footage (and clearing it)")
    lb.add_argument("--forget-ai", action="store_true", help="drop all stored AI verdicts")
    lb.add_argument("--wipe", action="store_true", help="delete the whole library (everything is re-analyzed)")
    lb.set_defaults(fn=cmd_library)

    sub.add_parser("styles", help="list styles").set_defaults(fn=cmd_styles)
    sub.add_parser("ui", help="open the interactive app (same as running tripshots with no arguments)"
                   ).set_defaults(fn=lambda a: __import__("tripshots.tui", fromlist=["run"]).run())
    fd = sub.add_parser("find", help="find footage by place, people and dates; saves a selection for `make sel:<id>`")
    fd.add_argument("folders", nargs="*", help="where to look (default: your footage folders, see `tripshots footage`)")
    fd.add_argument("--place", help='a place name: "Yellowstone National Park", "Lisbon", "Banff"')
    fd.add_argument("--near", metavar="LAT,LON", help="instead of a name: around a point")
    fd.add_argument("--radius", type=float, default=10, help="km around --near (default 10)")
    fd.add_argument("--people", nargs="+", metavar="NAME", help="who must be in it: me, mom, ... (see `tripshots people`)")
    fd.add_argument("--any-people", action="store_true", help="any of --people instead of all of them")
    fd.add_argument("--since", help="YYYY-MM-DD")
    fd.add_argument("--until", help="YYYY-MM-DD")
    fd.add_argument("--kind", choices=["both", "photo", "video"], default="both")
    fd.add_argument("--text", help="words in the folder/file/place name")
    fd.add_argument("--only-matching", action="store_true",
                    help="don't add same-day files without GPS (default: added, so phone clips come along)")
    fd.add_argument("--name", help="label for the selection (used in the reel's file name)")
    fd.add_argument("--sheet", action="store_true", help="also draw a contact sheet of what was found")
    fd.add_argument("--list", action="store_true", help="also print every file")
    fd.set_defaults(fn=cmd_find)

    tp = sub.add_parser("trips", help="your footage grouped into trips (dates, places, counts)")
    tp.add_argument("folders", nargs="*")
    tp.add_argument("--no-names", action="store_true", help="skip place-name lookups")
    tp.set_defaults(fn=cmd_trips)

    ft = sub.add_parser("footage", help="show or set the folders `find` and agents search by default")
    ft.add_argument("folders", nargs="*")
    ft.set_defaults(fn=cmd_footage)

    pp = sub.add_parser("people", help="recognise people in your footage (on this computer): add me / discover / name")
    pp.add_argument("action", choices=["list", "add", "discover", "name", "forget", "who"])
    pp.add_argument("args", nargs="*", help="add: <name> <photos...>; name: <cluster> <name>; discover/who: [folders]")
    pp.set_defaults(fn=cmd_people)

    ed = sub.add_parser("edits", help="finish a reel in Instagram's Edits app (Mac): package / tools / probe / push")
    ed.add_argument("action", choices=["package", "tools", "probe", "push"],
                    help="package: picture + clips + text + audio for Edits; tools: list Edits' automation tools; "
                         "probe: draft the tool mapping; push: build the timeline in Edits")
    ed.add_argument("target", nargs="?", help="package: NAME.plan.json; push: the NAME.edits folder")
    ed.add_argument("-o", "--out", help="package: folder to write (default NAME.edits next to the plan)")
    ed.add_argument("--no-clips", action="store_true", help="package: only the full picture, not one clip per shot")
    ed.add_argument("--stage", action=argparse.BooleanOptionalAction, default=None,
                    help="package: also copy it where the sandboxed Edits app can open it (default: on a Mac with Edits)")
    ed.add_argument("--picture", action="store_true", help="push: one video clip instead of one per shot")
    ed.add_argument("--music", choices=["library", "file", "none"], default="library",
                    help="push: leave the song to add from Edits' library (default), or add music.m4a")
    ed.add_argument("--text-as", choices=["text", "image"], default="text",
                    help="push: add titles as editable Edits text (default) or as TripShots' styled images")
    ed.add_argument("--url", help=f"Edits automation server (default $TRIPSHOTS_EDITS_URL or http://127.0.0.1:19501/mcp)")
    ed.add_argument("--token", help="its token (default $TRIPSHOTS_EDITS_TOKEN)")
    ed.add_argument("-j", "--workers", type=int, default=2)
    ed.set_defaults(fn=cmd_edits)

    an = sub.add_parser("analyze", help="analyse photos and videos on their own (no reel): what's in them, quality, "
                        "people, places -> media.jsonl for TripShots and other apps")
    an.add_argument("inputs", nargs="*", help="folders, files or sel:<id> (default: your footage folders)")
    an.add_argument("-o", "--out", help="output folder (default ~/.tripshots/analysis/<name>/)")
    an.add_argument("-b", "--backend", choices=["auto", "claude-cli", "api", "minimax", "none"],
                    help="AI that describes the shots (default: settings)")
    an.add_argument("--no-ai", action="store_true", help="technical analysis only (no AI descriptions)")
    an.add_argument("--no-faces", action="store_true", help="don't look for faces")
    an.add_argument("--no-places", action="store_true", help="don't look up place names (OpenStreetMap)")
    an.add_argument("--cached", action="store_true",
                    help="no new work: export only what's already analysed (no AI calls, no new files decoded)")
    an.add_argument("--print", action="store_true", help="also print every record")
    an.add_argument("--rescore", action="store_true", help="ask the AI again about every shot")
    an.add_argument("--watch", choices=["auto", "gemini", "off"])
    an.add_argument("--exclude", action="append", metavar="GLOB", default=[])
    an.add_argument("--since", metavar="YYYY-MM-DD")
    an.add_argument("--until", metavar="YYYY-MM-DD")
    an.add_argument("--no-recursive", action="store_true")
    an.add_argument("--include-live-photos", action="store_true")
    an.set_defaults(fn=cmd_analyze)

    ak = sub.add_parser("ask", help='plain language: tripshots ask "a reel about my days in Yellowstone"')
    ak.add_argument("request", nargs="+")
    ak.add_argument("-m", "--music", help="audio file or reel link (default: the AI picks from TRIPSHOTS_MUSIC)")
    ak.add_argument("-b", "--backend", choices=["auto", "claude-cli", "api", "minimax"])
    ak.add_argument("--render", action="store_true", help="render straight away (default: plan + storyboard)")
    ak.add_argument("--find-only", action="store_true", help="only find the footage (selection + contact sheet)")
    ak.add_argument("-j", "--workers", type=int, default=2)
    ak.set_defaults(fn=cmd_ask)

    mc = sub.add_parser("mcp", help="run as an MCP server for AI agents (Claude Desktop/Code, OpenClaw, ...)")
    mc.add_argument("--http", metavar="HOST:PORT",
                    help="serve over HTTP instead of stdio (e.g. 127.0.0.1:8765; other hosts need TRIPSHOTS_MCP_TOKEN)")
    mc.set_defaults(fn=lambda a: __import__("tripshots.mcp_server", fromlist=["main"]).main(a.http))

    sub.add_parser("doctor", help="check dependencies").set_defaults(fn=cmd_doctor)

    return p


def _run(p, a) -> None:
    if getattr(a, "encoder", None):
        os.environ["TRIPSHOTS_ENCODER"] = a.encoder  # also reaches the subprocesses
    if hasattr(a, "inputs"):  # blank lines in an @list.txt must not become "current folder"
        a.inputs = [x.strip() for x in a.inputs if x.strip() and not x.strip().startswith("#")]
        if not a.inputs and a.fn is not cmd_analyze:  # analyze defaults to the footage folders
            p.error("no input folders given")
    util.VERBOSE = a.verbose
    try:
        a.fn(a)
    except util.ReelError as e:
        util.log(f"error: {e}")
        sys.exit(2)
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
