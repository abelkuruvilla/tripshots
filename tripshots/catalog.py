"""What's in your footage: find files by place, date and the people in them, and group them into trips.

This is the layer an AI agent talks to ("a reel about my days in Yellowstone", "a reel of the photos
I'm in"): it turns such a request into a *selection* (a saved list of files) that `make` accepts
as `@<selection id>`.

Place matching uses three signals, any one is enough:
  1. GPS inside the place's outline (OpenStreetMap search, cached; "Yellowstone National Park"),
  2. the place name in the folder or file name ("Trips/Yellowstone 2025/..."),
  3. the place name in the file's reverse-geocoded name (cached from earlier runs).
With whole_days, files without GPS from the same days are added (between the first and last matching
file of each day, +-2 h), so phone videos and camera clips with no GPS come along; files whose GPS
is far from the place are not.
"""
from __future__ import annotations

import json
import math
import os
import re
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from . import library as lib
from .config import HOME
from .util import ReelError, ffmpeg_base, log, read_json, run, short_hash, write_json

SEL_DIR = HOME / "selections"
WORK = HOME / "catalog"
THUMBS = lib.LIB_DIR / "catalog_thumbs"


# ------------------------------------------------------------------ footage roots
def footage_roots() -> list[Path]:
    """Folders the agent may search when none are given: TRIPSHOTS_FOOTAGE (path-separated list),
    then the app's recent folders."""
    env = os.environ.get("TRIPSHOTS_FOOTAGE", "")
    roots = [Path(p).expanduser() for p in env.split(os.pathsep) if p.strip()]
    if not roots:
        st = read_json(HOME / "tui.json", {}) or {}
        for r in st.get("recent", []) or st.get("recent_sources", []) or []:
            for p in (r if isinstance(r, list) else str(r).split("|")):
                if p:
                    roots.append(Path(p).expanduser())
    seen, out = set(), []
    for r in roots:
        if r.exists() and str(r) not in seen:
            seen.add(str(r))
            out.append(r)
    return out


def set_footage_roots(folders: list[str]) -> list[str]:
    from .config import write_env
    paths = [str(Path(f).expanduser().resolve()) for f in folders]
    missing = [p for p in paths if not Path(p).exists()]
    if missing:
        raise ReelError(f"not found: {', '.join(missing)}")
    write_env({"TRIPSHOTS_FOOTAGE": os.pathsep.join(paths)})
    os.environ["TRIPSHOTS_FOOTAGE"] = os.pathsep.join(paths)
    return paths


def _roots(folders) -> list[Path]:
    roots = [Path(f).expanduser() for f in (folders or [])] or footage_roots()
    if not roots:
        raise ReelError("no footage folders known: pass folders, or set them once "
                        "(`tripshots footage ~/Trips /Volumes/SSD/Footage`)")
    return roots


# ------------------------------------------------------------------ records
def records(folders=None, opts: dict | None = None) -> list[dict]:
    """Every usable photo/video under the folders with its time, GPS and (cached) place name.
    Metadata comes from the shared library, so after the first scan this only stats files."""
    from .media import ingest
    WORK.mkdir(parents=True, exist_ok=True)
    try:
        recs = ingest(_roots(folders), WORK, opts or {})
    except ReelError as e:
        if "No photos or videos" in str(e):
            return []
        raise
    places = read_json(HOME / "geocode_cache.json", {}) or {}
    for r in recs:
        r["time"] = _dt(r.get("created"))
        g = r.get("gps")
        if g:
            r["place"] = places.get(f"{g[0]:.3f},{g[1]:.3f}") or places.get(_cell_key(g))
    return recs


def _dt(s) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "")[:19])
    except ValueError:
        return None


def _cell(g, deg=0.02):
    return (round(g[0] / deg) * deg, round(g[1] / deg) * deg)


def _cell_key(g):
    c = _cell(g)
    return f"{c[0]:.3f},{c[1]:.3f}"


def name_places(recs: list[dict], limit: int = 120) -> int:
    """Reverse-geocode GPS cells (~2 km) that have no name yet (cached; at most `limit` lookups)."""
    from .geo import place_name
    todo = []
    for r in recs:
        if r.get("gps") and not r.get("place"):
            k = _cell(r["gps"])
            if k not in todo:
                todo.append(k)
    named = {}
    for k in todo[:limit]:
        named[k] = place_name(*k)
        if named[k] is None and len(named) == 1:
            break  # offline
    for r in recs:
        if r.get("gps") and not r.get("place"):
            r["place"] = named.get(_cell(r["gps"]))
    return len(named)


def haversine(a, b) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(min(1.0, h)))


# ------------------------------------------------------------------ place matching
def _words(s: str) -> list[str]:
    stop = {"the", "of", "in", "at", "my", "national", "park", "state", "city", "trip", "and"}
    w = [x for x in re.findall(r"[a-z0-9]+", s.lower()) if len(x) > 2 and x not in stop]
    return w or re.findall(r"[a-z0-9]+", s.lower())


def place_matcher(place: str):
    """-> (fn(record) -> reason or None, description of what the place resolved to)."""
    from .geo import search
    words = _words(place)
    hit = search(place)
    shape = None
    if hit and hit.get("shape"):
        try:
            from shapely.geometry import Point, shape as mkshape
            geom = mkshape(hit["shape"])
            if geom.geom_type in ("Polygon", "MultiPolygon"):
                shape = (geom.buffer(0.01), Point)  # ~1 km slack: viewpoints on the boundary road
        except Exception:
            shape = None
    bbox = hit.get("bbox") if hit else None
    centre = (hit["lat"], hit["lon"]) if hit else None

    def match(r):
        g = r.get("gps")
        if g and shape:
            if shape[0].contains(shape[1](g[1], g[0])):
                return "gps"
        elif g and bbox and hit.get("type") not in ("river", "stream", "road"):
            s, n, w, e = bbox
            if s <= g[0] <= n and w <= g[1] <= e:
                return "gps"
            if centre and haversine(g, centre) < 3:
                return "gps"
        hay = r["path"].lower()
        if all(w in hay for w in words):
            return "folder"
        if r.get("place") and all(w in r["place"].lower() for w in words):
            return "place name"
        return None

    desc = hit["name"] if hit else f'"{place}" (no map match: folder and place names only)'
    return match, desc, centre


# ------------------------------------------------------------------ find
def find(folders=None, place: str | None = None, near: list[float] | None = None, radius_km: float = 10,
         people: list[str] | None = None, people_mode: str = "all", date_from: str | None = None,
         date_to: str | None = None, kinds: str = "both", whole_days: bool = True, text: str | None = None,
         label: str | None = None, max_people_scan: int = 4000) -> dict:
    """Find footage and save it as a selection. Returns a summary for the agent (counts, days,
    places, people) and the selection id to pass to `make sel:<id>`."""
    recs = records(folders, {"since": date_from, "until": date_to})
    if kinds in ("photo", "photos"):
        recs = [r for r in recs if r["kind"] == "photo"]
    elif kinds in ("video", "videos"):
        recs = [r for r in recs if r["kind"] == "video"]
    total = len(recs)
    notes: list[str] = []
    why: dict[str, str] = {}

    picked = recs
    if text:
        words = _words(text)
        picked = [r for r in picked if all(w in (r["path"] + " " + (r.get("place") or "")).lower() for w in words)]
    if place or near:
        if place:
            match, desc, centre = place_matcher(place)
            notes.append(f"place: {desc}")
        else:
            centre = tuple(near)

            def match(r):
                return "gps" if r.get("gps") and haversine(r["gps"], centre) <= radius_km else None
            notes.append(f"within {radius_km:g} km of {near[0]:.4f}, {near[1]:.4f}")
        core = []
        for r in picked:
            m = match(r)
            if m:
                why[r["path"]] = m
                core.append(r)
        if whole_days and core:
            extra = _same_days(core, [r for r in picked if r["path"] not in why], centre)
            for r in extra:
                why[r["path"]] = "same day, no GPS"
            if extra:
                notes.append(f"{len(extra)} files without GPS added from the same days")
            core += extra
        picked = core
    if people:
        from . import people as ppl
        people = [ppl.canonical(p) for p in people]
        if len(picked) > max_people_scan:
            raise ReelError(f"{len(picked)} files to check for faces: narrow it down with a place or dates first")
        found = ppl.who_is_in(picked)
        keep = []
        for r in picked:
            names = found.get(r["path"], [])
            r["people"] = names
            ok = all(p in names for p in people) if people_mode == "all" else any(p in names for p in people)
            if ok:
                keep.append(r)
        missing = [p for p in people if not ppl.known(p)]
        if missing:
            notes.append(f"unknown people: {', '.join(missing)} (enroll them first: `tripshots people add`)")
        notes.append(f"people: {' and '.join(people) if people_mode == 'all' else ' or '.join(people)}")
        picked = keep
    picked.sort(key=lambda r: (r.get("created") or "", r["path"]))
    q = {"place": place, "near": near, "radius_km": radius_km if near else None, "people": people,
         "date_from": date_from, "date_to": date_to, "kinds": kinds, "whole_days": whole_days, "text": text,
         "folders": [str(f) for f in _roots(folders)]}
    return _save_selection(picked, q, total, notes, why, label)


def _same_days(core: list[dict], rest: list[dict], centre) -> list[dict]:
    spans: dict[str, list[datetime]] = {}
    pts = [r["gps"] for r in core if r.get("gps")]
    for r in core:
        if r.get("time"):
            spans.setdefault(r["time"].date().isoformat(), []).append(r["time"])
    out = []
    for r in rest:
        t = r.get("time")
        if not t or r.get("created_from") == "mtime":
            continue
        day = spans.get(t.date().isoformat())
        if not day or not (min(day) - timedelta(hours=2) <= t <= max(day) + timedelta(hours=2)):
            continue
        g = r.get("gps")
        if g and pts and min(haversine(g, p) for p in pts) > 50:
            continue  # it has GPS and it's somewhere else (the drive home, another town)
        out.append(r)
    return out


def _save_selection(picked, query, total, notes, why, label) -> dict:
    SEL_DIR.mkdir(parents=True, exist_ok=True)
    sid = short_hash(json.dumps(query, sort_keys=True, default=str) + "|".join(r["path"] for r in picked), 8)
    if not label:
        bits = [query.get("place"), " ".join(query.get("people") or []) or None, query.get("text"),
                query.get("date_from")]
        label = "-".join(re.sub(r"[^A-Za-z0-9]+", "", str(b).title()) for b in bits if b) or "selection"
    days = Counter(r["created"][:10] for r in picked if r.get("created"))
    places = Counter(r["place"] for r in picked if r.get("place"))
    ppl = Counter(n for r in picked for n in r.get("people", []))
    summary = {
        "selection": sid, "label": label, "count": len(picked), "searched": total,
        "photos": sum(r["kind"] == "photo" for r in picked), "videos": sum(r["kind"] == "video" for r in picked),
        "video_seconds": round(sum(r.get("duration") or 0 for r in picked if r["kind"] == "video")),
        "first": picked[0]["created"] if picked else None, "last": picked[-1]["created"] if picked else None,
        "days": dict(sorted(days.items())), "places": dict(places.most_common(8)),
        "people": dict(ppl.most_common()), "with_gps": sum(1 for r in picked if r.get("gps")),
        "matched_by": dict(Counter(why.get(r["path"], "filter") for r in picked)), "notes": notes,
        "use_with": f"tripshots make sel:{sid} -m <music>",
    }
    files = [{"path": r["path"], "kind": r["kind"], "created": r.get("created"), "gps": r.get("gps"),
              "place": r.get("place"), "people": r.get("people"), "why": why.get(r["path"]),
              "duration": r.get("duration"), "sig": r.get("sig"), "still": r.get("still")} for r in picked]
    write_json(SEL_DIR / f"{sid}.json", {"id": sid, "label": label, "query": query, "created": time.time(),
                                          "summary": summary, "files": files})
    return summary


def load_selection(sid: str) -> dict:
    sid = sid.strip().removeprefix("sel:").lstrip("@")
    p = SEL_DIR / f"{sid}.json"
    sel = read_json(p)
    if not sel:
        raise ReelError(f"unknown selection sel:{sid} (run `tripshots find ...` first)")
    return sel


def selection_paths(sid: str) -> tuple[list[Path], str]:
    sel = load_selection(sid)
    paths = [Path(f["path"]) for f in sel["files"] if Path(f["path"]).exists()]
    if not paths:
        raise ReelError(f"selection sel:{sid} has no files left on disk")
    if len(paths) < len(sel["files"]):
        log(f"selection sel:{sid}: {len(sel['files']) - len(paths)} file(s) no longer on disk")
    return paths, sel.get("label") or sid


def expand_inputs(inputs: list[str]) -> tuple[list[Path], str | None]:
    """make/scan/clone inputs: folders, files and selections (`sel:<id>` from `tripshots find`)."""
    out, label = [], None
    for s in inputs:
        if str(s).startswith("sel:"):
            paths, label = selection_paths(str(s))
            out += paths
        else:
            out.append(Path(s))
    return out, label


# ------------------------------------------------------------------ trips
def trips(folders=None, gap_days: float = 2.0, name: bool = True) -> list[dict]:
    """Group the footage into trips (a new trip after a 2-day gap, or a >500 km jump after a night)."""
    recs = [r for r in records(folders) if r.get("time") and r.get("created_from") != "mtime"]
    recs.sort(key=lambda r: r["time"])
    if name:
        name_places(recs)
    groups: list[list[dict]] = []
    last_gps = None
    for r in recs:
        if groups:
            prev = groups[-1][-1]
            gap = (r["time"] - prev["time"]).total_seconds() / 86400
            far = r.get("gps") and last_gps and haversine(r["gps"], last_gps) > 500 and gap > 0.4
            if gap > gap_days or far:
                groups.append([])
        else:
            groups.append([])
        groups[-1].append(r)
        if r.get("gps"):
            last_gps = r["gps"]
    out = []
    for g in groups:
        places = Counter(r["place"] for r in g if r.get("place"))
        days = Counter(r["time"].date().isoformat() for r in g)
        per_day = {}
        for d in sorted(days):
            pd = Counter(r["place"] for r in g if r["time"].date().isoformat() == d and r.get("place"))
            per_day[d] = {"files": days[d], "places": [p for p, _ in pd.most_common(3)]}
        top = [p for p, _ in places.most_common(4)]
        gps = [r["gps"] for r in g if r.get("gps")]
        out.append({"from": g[0]["time"].date().isoformat(), "to": g[-1]["time"].date().isoformat(),
                    "days": len(days), "files": len(g), "photos": sum(r["kind"] == "photo" for r in g),
                    "videos": sum(r["kind"] == "video" for r in g), "places": top,
                    "centre": [round(sum(p[0] for p in gps) / len(gps), 4), round(sum(p[1] for p in gps) / len(gps), 4)]
                    if gps else None,
                    "folders": [f for f, _ in Counter(str(Path(r["path"]).parent) for r in g).most_common(3)],
                    "per_day": per_day})
    return out


# ------------------------------------------------------------------ contact sheet
def thumb(f: dict, size: int = 320) -> Path | None:
    THUMBS.mkdir(parents=True, exist_ok=True)
    out = THUMBS / f"{f.get('sig') or short_hash(f['path'])}_{size}.jpg"
    if out.exists():
        return out
    try:
        if f["kind"] == "photo":
            from PIL import Image, ImageOps
            src = f.get("still") or f["path"]
            with Image.open(src) as im:
                im = ImageOps.exif_transpose(im).convert("RGB")
                im.thumbnail((size, size))
                im.save(out, "JPEG", quality=82)
        else:
            t = max(0.0, float(f.get("duration") or 2) * 0.4)
            run(ffmpeg_base() + ["-ss", f"{t:.2f}", "-i", f["path"], "-frames:v", "1",
                                 "-vf", f"scale={size}:{size}:force_original_aspect_ratio=decrease", str(out)])
    except Exception:
        return None
    return out if out.exists() else None


def contact_sheet(sid: str, max_items: int = 24, out: Path | None = None) -> Path | None:
    """A grid of the selection (spread over its whole time span), labelled with date and kind."""
    from PIL import Image, ImageDraw
    sel = load_selection(sid)
    files = sel["files"]
    if not files:
        return None
    step = max(1, len(files) / max_items)
    pick = [files[int(i * step)] for i in range(min(max_items, len(files)))]
    cols, cw, ch = 6, 220, 220
    rows = math.ceil(len(pick) / cols)
    sheet = Image.new("RGB", (cols * cw, rows * (ch + 22) + 30), (18, 18, 18))
    d = ImageDraw.Draw(sheet)
    d.text((8, 8), f"sel:{sid} {sel.get('label', '')}: {len(files)} files "
                   f"(showing {len(pick)})", fill=(255, 214, 0))
    for i, f in enumerate(pick):
        x, y = (i % cols) * cw, 30 + (i // cols) * (ch + 22)
        t = thumb(f)
        if t:
            with Image.open(t) as im:
                im.thumbnail((cw - 8, ch - 8))
                sheet.paste(im, (x + (cw - im.width) // 2, y + (ch - im.height) // 2))
        lab = f"{(f.get('created') or '')[:10]} {'video ' if f['kind'] == 'video' else ''}{Path(f['path']).name[:18]}"
        d.text((x + 4, y + ch + 2), lab, fill=(220, 220, 220))
    out = out or SEL_DIR / f"{sid}.sheet.jpg"
    sheet.save(out, "JPEG", quality=85)
    return out
