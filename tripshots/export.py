"""Hand the edit to a real editor: CMX3600 EDL, OpenTimelineIO and a readable storyboard.md.

The plan's cuts, source in-points and speeds carry over, so the reel can be finished or tweaked in
DaVinci Resolve, Premiere or Final Cut (OTIO). Effects that only tripshots draws (text, grade, maps,
panels, freeze) are written as comments / markers, not rebuilt.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .util import log

FPS = 30


def tc(sec: float, fps: int = FPS) -> str:
    f = int(max(0.0, sec) * fps + 0.5)
    return f"{f // (3600 * fps):02d}:{f // (60 * fps) % 60:02d}:{f // fps % 60:02d}:{f % fps:02d}"


def _reel(name: str) -> str:
    r = re.sub(r"[^A-Za-z0-9]", "", Path(name).stem).upper()
    return (r[-8:] or "AX").ljust(8)


def _main_src(seg: dict) -> dict:
    """The clip that stands for a segment: itself, or a split-screen's first panel."""
    if seg.get("panel"):
        c = dict((seg.get("clips") or [{}])[0])
        c.setdefault("dur", seg["dur"])
        return c
    return seg


def events(plan: dict) -> list[dict]:
    out, rec = [], 0.0
    for i, s in enumerate(plan["segments"]):
        c = _main_src(s)
        dur = float(s["dur"])
        speed = float(c.get("speed", 1) or 1)
        still = c.get("kind") == "photo"
        src_in = 0.0 if still else float(c.get("in", 0))
        notes = []
        if s.get("panel"):
            notes.append(f"split screen {s['panel']} with {len(s.get('clips') or [])} clips; first clip shown")
        if s.get("trans_out"):
            notes.append(f"tripshots transition out: {s['trans_out']}")
        if s.get("incam_out"):
            notes.append("in-camera whip: cut inside the camera's swing")
        if s.get("ramp") and not s.get("panel"):
            from .retime import describe, hit_time, source_seconds
            speed = source_seconds(s) / dur  # average speed; the curve itself is in the note
            h = hit_time(s)
            notes.append(f"{describe(s)}" + (f", slow motion from {h - s['out_start']:.2f}s" if h else "")
                         + " (shown here at its average speed)")
        if still:
            notes.append(f"still photo, {s.get('kb') or s.get('layout') or 'ken burns'}")
        out.append({"n": i + 1, "src": c.get("src") or "", "still": still, "src_in": src_in,
                    "src_out": src_in + (dur if still else dur * speed), "speed": speed,
                    "rec_in": rec, "rec_out": rec + dur, "shot": s.get("shot_id") or c.get("shot_id"),
                    "notes": notes, "layout": s.get("layout"), "note": s.get("note", "")})
        rec += dur
    return out


def to_edl(plan: dict, title: str) -> str:
    base = 3600.0  # record side starts at 01:00:00:00, the editors' default
    lines = [f"TITLE: {title[:60]}", "FCM: NON-DROP FRAME", ""]
    n = 0
    for e in events(plan):
        n += 1
        reel = "BL      " if not e["src"] else _reel(e["src"])
        lines.append(f"{n:03d}  {reel} V     C        {tc(e['src_in'])} {tc(e['src_out'])} "
                     f"{tc(base + e['rec_in'])} {tc(base + e['rec_out'])}")
        if abs(e["speed"] - 1) > 0.001 and not e["still"]:
            lines.append(f"M2   {reel} {FPS * e['speed']:05.1f}    {tc(e['src_in'])}")
        if e["src"]:
            lines.append(f"* FROM CLIP NAME: {Path(e['src']).name}")
            lines.append(f"* SOURCE FILE: {e['src']}")
        for note in e["notes"]:
            lines.append(f"* {note}")
        lines.append("")
    m = plan.get("music") or {}
    if m.get("path"):
        n += 1
        start = float(m.get("start", 0))
        lines.append(f"{n:03d}  {_reel(m['path'])} A     C        {tc(start)} {tc(start + float(plan['duration']))} "
                     f"{tc(base)} {tc(base + float(plan['duration']))}")
        lines.append(f"* FROM CLIP NAME: {Path(m['path']).name}")
        lines.append(f"* SOURCE FILE: {m['path']}")
        lines.append("")
    return "\n".join(lines)


def to_otio(plan: dict, title: str, path: Path) -> Path | None:
    try:
        import opentimelineio as otio
    except ImportError:
        log("OTIO export skipped: pip install opentimelineio")
        return None
    RT, TR = otio.opentime.RationalTime, otio.opentime.TimeRange
    tl = otio.schema.Timeline(name=title)
    tl.global_start_time = RT(0, FPS)
    v = otio.schema.Track(name="Video", kind=otio.schema.TrackKind.Video)
    for e in events(plan):
        dur = e["rec_out"] - e["rec_in"]
        ref = otio.schema.ExternalReference(target_url=Path(e["src"]).resolve().as_uri()) if e["src"] \
            else otio.schema.MissingReference()
        clip = otio.schema.Clip(name=f"{e['n']:02d} {e['shot'] or ''} {Path(e['src']).name}".strip(),
                                media_reference=ref,
                                source_range=TR(RT(round(e["src_in"] * FPS), FPS), RT(round(dur * FPS), FPS)))
        if abs(e["speed"] - 1) > 0.001 and not e["still"]:
            clip.effects.append(otio.schema.LinearTimeWarp(time_scalar=e["speed"]))
        clip.metadata["tripshots"] = {"shot_id": e["shot"], "notes": e["notes"], "layout": e["layout"],
                                      "note": e["note"], "still": e["still"]}
        v.append(clip)
    tl.tracks.append(v)
    m = plan.get("music") or {}
    if m.get("path"):
        a = otio.schema.Track(name="Music", kind=otio.schema.TrackKind.Audio)
        a.append(otio.schema.Clip(name=Path(m["path"]).name,
                                  media_reference=otio.schema.ExternalReference(
                                      target_url=Path(m["path"]).resolve().as_uri()),
                                  source_range=TR(RT(round(float(m.get("start", 0)) * FPS), FPS),
                                                  RT(round(float(plan["duration"]) * FPS), FPS))))
        tl.tracks.append(a)
    for o in plan.get("overlays") or []:  # text and maps as markers on the video track
        if o.get("text") or o.get("type") == "map":
            mk = otio.schema.Marker(name=f"{o['type']}: {o.get('text') or o.get('title') or ''}".strip(),
                                    marked_range=TR(RT(round(float(o["start"]) * FPS), FPS),
                                                    RT(max(1, round(float(o.get("duration", 1)) * FPS)), FPS)))
            v.markers.append(mk)
    otio.adapters.write_to_file(tl, str(path))
    return path


def to_markdown(plan: dict, title: str) -> str:
    L = [f"# {title}", ""]
    m = plan.get("music") or {}
    g = plan.get("grade") or {}
    L.append(f"- **Length:** {float(plan['duration']):.1f} s at {plan.get('tempo', '?')} BPM, "
             f"{len(plan['segments'])} shots, style `{plan.get('style', '?')}`")
    if m.get("path"):
        L.append(f"- **Music:** {Path(m['path']).name} from {float(m.get('start', 0)):.2f} s")
    if g:
        L.append(f"- **Grade:** {g.get('look')} at {round(100 * float(g.get('strength', 1)))}% ({g.get('why', '')})")
    if plan.get("freeze"):
        L.append(f"- **Freeze-frame:** {plan['freeze']['t']:.2f} s")
    L += ["", "| # | time | dur | shot | source | in | speed | out | note |", "|---|---|---|---|---|---|---|---|---|"]
    for e, s in zip(events(plan), plan["segments"]):
        out = s.get("trans_out") or ("in-camera whip" if s.get("incam_out") else "cut")
        src = Path(e["src"]).name if e["src"] else "—"
        if s.get("panel"):
            src = f"{s['panel']}: " + ", ".join(Path(c.get("src", "")).name for c in s.get("clips") or [])
        note = (e["note"] or "").replace("|", "/")[:80]
        src_in = "photo" if e["still"] else f"{e['src_in']:.2f}"
        L.append(f"| {e['n']} | {e['rec_in']:.2f} | {e['rec_out'] - e['rec_in']:.2f} | {e['shot'] or ''} | {src} | "
                 f"{src_in} | {e['speed']:g} | {out} | {note} |")
    ov = [o for o in plan.get("overlays") or [] if o.get("text") or o.get("type") == "map"]
    if ov:
        L += ["", "## Text and maps", ""]
        for o in ov:
            L.append(f"- {float(o['start']):.2f}–{float(o['start']) + float(o.get('duration', 0)):.2f} s · "
                     f"**{o['type']}** · {o.get('text') or o.get('title') or o.get('mode', '')}")
    L.append("")
    return "\n".join(L)


def export(plan_path: Path, edl: bool = True, otio: bool = True, md: bool = True, quiet: bool = False) -> dict:
    plan_path = Path(plan_path)
    plan = json.loads(plan_path.read_text())
    stem = plan_path.name[:-len(".plan.json")] if plan_path.name.endswith(".plan.json") else plan_path.stem
    base = plan_path.with_name(stem)
    res = {}
    if edl:
        p = base.with_suffix(".edl")
        p.write_text(to_edl(plan, stem))
        res["edl"] = str(p)
    if otio:
        p = to_otio(plan, stem, base.with_suffix(".otio"))
        if p:
            res["otio"] = str(p)
    if md:
        p = base.with_name(stem + ".storyboard.md")
        p.write_text(to_markdown(plan, stem))
        res["storyboard_md"] = str(p)
    if not quiet:
        log("editor exports: " + ", ".join(Path(v).name for v in res.values()))
    return res
