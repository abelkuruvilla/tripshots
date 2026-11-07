"""The media analyzer: what is in each photo and video, as one app-neutral record per file.

    tripshots analyze ~/Trips /Volumes/SSD/Footage        # -> ~/.tripshots/analysis/<name>/media.jsonl

Each record (schema `tripshots.media/1`, tripshots/schemas/media.schema.json, docs/analysis.md) describes a file:
what it is (size, dimensions, duration, codec), when and where it was taken, which camera, which trip it belongs
to, who is in it, and for every shot in it (a photo is one shot, a video is split at its scene cuts) the technical
quality, colours, faces and an AI description (caption, tags, subjects with boxes, scene, light, people, text,
landmark, aesthetic score, issues). Uses specific to one app live under `uses` (`uses.reel` for TripShots' reels).

Everything is cached by file content in the library, so a second run only analyses new files and reels made
later reuse the same AI verdicts. Other programs read media.jsonl (any language) or use `load()` from Python.
"""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from . import library as lib
from .config import HOME, cache_dir_for
from .util import ReelError, log, read_json, short_hash, write_json

SCHEMA_ID = "tripshots.media/1"
SCHEMA_FILE = Path(__file__).parent / "schemas" / "media.schema.json"
TECH_VERSION = 3
OUT_ROOT = HOME / "analysis"
GENERATOR = "tripshots"


# ================================================================== technical analyzers
def edge_sharpness(gray: np.ndarray) -> float | None:
    """Focus, independent of how much detail or contrast a picture has: at the strongest edges, the ratio of the
    Laplacian to the gradient is about 1 / (width of the edge's blur). Calibrated on real photos at 480 px wide:
    crisp ones measure 0.65-1.4, a 2 px Gaussian blur drops them to 0.2-0.6, 4 px to 0.1-0.35.
    None for nearly flat pictures (no edges to judge)."""
    g = gray.astype(np.float32)
    gx, gy = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    mag = np.hypot(gx, gy)
    m = mag >= max(float(np.percentile(mag, 95)), 20.0)
    if int(m.sum()) < 50:
        return None
    lap = cv2.dilate(np.abs(cv2.Laplacian(g, cv2.CV_32F, ksize=3)), np.ones((3, 3), np.uint8))
    return float(np.median(lap[m] / (mag[m] + 1e-3)))


def sharpness_score(edge: float | None, lap_var: float) -> float:
    """0 (blurred) .. 1 (crisp)."""
    if edge is None:  # flat picture: fall back on overall detail
        lo, hi = math.log1p(15), math.log1p(400)
        return round(float(np.clip((math.log1p(max(0.0, lap_var)) - lo) / (hi - lo), 0, 1)), 3)
    return round(float(np.clip((edge - 0.25) / 0.5, 0, 1)), 3)


def sharpness_label(edge: float | None, lap_var: float) -> str:
    if edge is None:
        return "blurry" if lap_var < 30 else ("soft" if lap_var < 100 else "sharp")
    return "blurry" if edge < 0.3 else ("soft" if edge < 0.55 else "sharp")


def dhash(gray: np.ndarray) -> str:
    """64-bit difference hash: near-identical pictures (resized, recompressed, re-exported) differ in < 10 bits."""
    small = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
    bits = (small[:, 1:] > small[:, :-1]).flatten()
    return f"{int(''.join('1' if b else '0' for b in bits), 2):016x}"


def hamming(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def palette(rgb: np.ndarray, k: int = 5) -> list[dict]:
    """Dominant colours (k-means in Lab on a 96 px thumbnail), largest share first."""
    h, w = rgb.shape[:2]
    s = 96 / max(h, w)
    small = cv2.resize(rgb, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA)
    lab = cv2.cvtColor(small, cv2.COLOR_RGB2LAB).reshape(-1, 3).astype(np.float32)
    k = min(k, len(lab))
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 0.5)
    cv2.setRNGSeed(7)
    _, labels, centers = cv2.kmeans(lab, k, None, crit, 3, cv2.KMEANS_PP_CENTERS)
    counts = np.bincount(labels.flatten(), minlength=k)
    rgbc = cv2.cvtColor(centers.reshape(1, -1, 3).astype(np.uint8), cv2.COLOR_LAB2RGB).reshape(-1, 3)
    out = []
    for i in np.argsort(-counts):
        r, g, b = (int(x) for x in rgbc[i])
        out.append({"hex": f"#{r:02x}{g:02x}{b:02x}", "share": round(float(counts[i] / counts.sum()), 3)})
    return out


def technical(rgb: np.ndarray, metrics: dict | None = None) -> dict:
    """Quality and colour of one picture (a photo, or a video shot's middle frame)."""
    h, w = rgb.shape[:2]
    if w != 480:
        rgb = cv2.resize(rgb, (480, max(1, int(480 * h / w))), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    lap = float(metrics["sharp"]) if metrics and "sharp" in metrics else float(cv2.Laplacian(gray, cv2.CV_64F).var())
    edge = edge_sharpness(gray)
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    a, b = float(lab[..., 1].mean() - 128), float(lab[..., 2].mean() - 128)
    bright = float(gray.mean() / 255)
    hi, lo = float((gray >= 250).mean()), float((gray <= 5).mean())
    from .shots import _colorfulness
    col = float(metrics["color"]) if metrics and "color" in metrics else _colorfulness(rgb)
    return {
        "sharpness": sharpness_score(edge, lap), "sharpness_label": sharpness_label(edge, lap),
        "edge_sharpness": round(edge, 3) if edge is not None else None, "laplacian_var": round(lap, 1),
        "brightness": round(bright, 3),
        "exposure_label": "dark" if bright < 0.18 else ("bright" if bright > 0.8 else "normal"),
        "highlights_clipped": round(hi, 4), "shadows_clipped": round(lo, 4),
        "contrast": round(float(gray.std() / 128), 3),
        "colorfulness": round(min(1.0, col / 100), 3),
        "warmth": round(b / 40, 3), "tint": round(a / 40, 3),
        "temperature_label": "warm" if b > 8 else ("cool" if b < -5 else "neutral"),
        "palette": palette(rgb), "dhash": dhash(gray),
    }


def motion_label(m: dict) -> str:
    pan, shake = float(m.get("pan", 0)), float(m.get("shake", 0))
    if shake > 0.006:
        return "shaky"
    if pan > 0.004:
        return "moving"
    if shake > 0.002:
        return "handheld"
    return "steady"


# ------------------------------------------------------------------ camera metadata
_EXIF = {271: "make", 272: "model"}
_EXIF_SUB = {42036: "lens", 37386: "focal_length_mm", 41989: "focal_length_35mm", 33437: "aperture",
             33434: "exposure_s", 34855: "iso", 37385: "flash"}


def _num(v):
    try:
        return round(float(v), 4)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def camera_info(path: str, kind: str) -> dict:
    out: dict = {}
    try:
        if kind == "photo":
            from PIL import Image
            try:
                import pillow_heif  # noqa: F401
                pillow_heif.register_heif_opener()
            except ImportError:
                pass
            with Image.open(path) as im:
                ex = im.getexif()
                for tag, k in _EXIF.items():
                    if ex.get(tag):
                        out[k] = str(ex[tag]).strip("\x00 ")
                sub = ex.get_ifd(0x8769)
                for tag, k in _EXIF_SUB.items():
                    v = sub.get(tag)
                    if v is None:
                        continue
                    if k in ("lens",):
                        out[k] = str(v).strip("\x00 ")
                    elif k == "flash":
                        out[k] = bool(int(v) & 1)
                    elif k == "iso":
                        out[k] = int(v[0] if isinstance(v, tuple) else v)
                    else:
                        out[k] = _num(v)
        else:
            p = subprocess.run(["ffprobe", "-v", "error", "-show_format", "-of", "json", path],
                               capture_output=True, text=True, timeout=30)
            tags = {k.lower(): v for k, v in (json.loads(p.stdout or "{}").get("format", {}).get("tags") or {}).items()}
            for k, names in (("make", ("com.apple.quicktime.make", "make", "com.android.manufacturer")),
                             ("model", ("com.apple.quicktime.model", "model", "com.android.model")),
                             ("software", ("com.apple.quicktime.software",))):
                for n in names:
                    if tags.get(n):
                        out[k] = tags[n]
                        break
    except Exception:
        pass
    return out


# ------------------------------------------------------------------ per-file technical pass (cached)
def file_technical(rec: dict, shots: list[dict]) -> dict:
    """{camera, shots: {t0: technical}} for one file; cached by content (TECH_VERSION)."""
    cached = lib.get_analysis(rec["sig"], TECH_VERSION)
    keys = {f"{float(s['t0']):.3f}" for s in shots}
    if cached and keys <= set(cached.get("shots", {})):
        return cached
    out = {"camera": camera_info(rec["path"], rec["kind"]), "shots": dict((cached or {}).get("shots", {}))}
    for s in shots:
        k = f"{float(s['t0']):.3f}"
        if k in out["shots"]:
            continue
        img = cv2.imread(str(s["thumb"]))
        if img is None:
            continue
        out["shots"][k] = technical(cv2.cvtColor(img, cv2.COLOR_BGR2RGB), s.get("metrics"))
    lib.put_analysis(rec["sig"], TECH_VERSION, out)
    return out


def similar_groups(items: list[tuple[str, str]], max_bits: int = 8) -> dict[str, str]:
    """[(shot id, dhash)] -> {shot id: group id} for near-duplicates (groups of 2+ only)."""
    parent = {i: i for i, _ in items}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for n, (i, h) in enumerate(items):
        for j, h2 in items[n + 1:]:
            if hamming(h, h2) <= max_bits:
                parent[find(j)] = find(i)
    groups: dict[str, list[str]] = {}
    for i, _ in items:
        groups.setdefault(find(i), []).append(i)
    out = {}
    for root, members in groups.items():
        if len(members) > 1:
            gid = "dup-" + short_hash(root, 8)
            for m in members:
                out[m] = gid
    return out


# ================================================================== the run
def analyze(inputs: list[Path], backend_name: str | None = None, ai: bool = True, faces: bool = True,
            places: bool = True, watch_mode: str | None = None, rescore: bool = False, cached: bool = False,
            out_dir: Path | None = None, label: str | None = None, source_opts: dict | None = None) -> dict:
    """Analyse footage (incrementally) and write media.jsonl + summary.json + schema.json."""
    from . import ai as ai_mod
    from . import catalog
    from .media import ingest
    from .shots import ANALYSIS_VERSION, analyze as analyze_shots, heuristic_scores
    t_start = time.time()
    work = cache_dir_for(inputs)
    media = ingest(inputs, work, source_opts or {})
    if cached:
        media = [m for m in media if lib.get_shots(m["sig"], ANALYSIS_VERSION) is not None]
        log(f"cached only: {len(media)} file(s) already analysed")
    shots = analyze_shots(media, work) if media else []

    # AI descriptions (one pass, shared with reels; older thinner verdicts are re-asked)
    backend = None
    if ai and not cached:
        backend = ai_mod.get_backend(backend_name)
    verdicts: dict[str, dict] = {}
    if backend:
        try:
            verdicts = ai_mod.score_shots(shots, backend, work, rescore=rescore, min_version=ai_mod.AI_VERSION)
        except Exception as e:
            log(f"AI analysis failed ({e}); technical analysis only")
    elif ai:
        stored = lib.get_scores([lib.shot_key(s) for s in shots])
        verdicts = {s["id"]: stored[lib.shot_key(s)] for s in shots if lib.shot_key(s) in stored}
    heur = heuristic_scores(shots)
    for s in shots:
        s["ai"] = verdicts.get(s["id"]) or {**heur[s["id"]], "v": 0}

    # Gemini watch (optional): best moments, shake, audio
    from . import watch as watch_mod
    mode = watch_mode or os.environ.get("TRIPSHOTS_WATCH", "auto")
    wlogs = {}
    if mode != "off" and not cached and (mode == "gemini" or watch_mod.api_key()):
        wlogs = watch_mod.watch_media([m for m in media if m["kind"] == "video"], work)
    elif mode != "off":
        for m in media:
            c = read_json(watch_mod._cache(m["sig"])) if m["kind"] == "video" else None
            if c:
                wlogs[m["sig"]] = c
    watch_mod.apply(shots, wlogs)

    # records the catalog knows (time, place), faces, places, trips
    recs = {m["sig"]: {**m, "time": catalog._dt(m.get("created"))} for m in media}
    gc = read_json(HOME / "geocode_cache.json", {}) or {}
    for r in recs.values():
        g = r.get("gps")
        if g:
            r["place"] = gc.get(f"{g[0]:.3f},{g[1]:.3f}") or gc.get(catalog._cell_key(g))
    if places and not cached:
        catalog.name_places(list(recs.values()), limit=200)
    face_map: dict[str, list] = {}
    if faces:
        from . import people as ppl
        try:
            if cached:
                face_map = {r["path"]: (read_json(ppl.FACE_DIR / f"{r['sig']}.json") or {}).get("faces", [])
                            for r in recs.values() if (ppl.FACE_DIR / f"{r['sig']}.json").exists()}
            else:
                face_map = ppl.index(list(recs.values()))
        except Exception as e:
            log(f"faces skipped ({e})")
    trip_of = {}
    dated = sorted([r for r in recs.values() if r["time"] and r.get("created_from") != "mtime"], key=lambda r: r["time"])
    for g in catalog.group_trips(dated):
        t = catalog._trip_summary(g)
        for r in g:
            trip_of[r["sig"]] = {"id": t["id"], "from": t["from"], "to": t["to"]}

    # technical pass + records
    by_file: dict[str, list[dict]] = {}
    for s in shots:
        by_file.setdefault(s["sig"], []).append(s)
    tech = {sig: file_technical(recs[sig], ss) for sig, ss in by_file.items() if sig in recs}
    dup = similar_groups([(lib.shot_key(s), tech[s["sig"]]["shots"].get(f"{float(s['t0']):.3f}", {}).get("dhash"))
                          for s in shots if tech.get(s["sig"], {}).get("shots", {}).get(f"{float(s['t0']):.3f}")])
    records = [build_record(recs[sig], ss, tech.get(sig, {}), face_map.get(recs[sig]["path"]), trip_of.get(sig), dup)
               for sig, ss in by_file.items() if sig in recs]
    records.sort(key=lambda r: (r["captured"]["time"] or "", r["path"]))

    # write
    name = label or (inputs[0].resolve().name if len(inputs) == 1 else f"{inputs[0].resolve().name}+{len(inputs) - 1}")
    out = Path(out_dir) if out_dir else OUT_ROOT / f"{name}-{short_hash('|'.join(sorted(map(str, inputs))), 6)}"
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "media.jsonl", "w") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    write_json(out / "schema.json", json.loads(SCHEMA_FILE.read_text()))
    summary = make_summary(records, inputs, backend, time.time() - t_start)
    write_json(out / "summary.json", summary)
    log(f"analysis: {len(records)} files, {sum(len(r['shots']) for r in records)} shots -> {out}")
    return {"output": str(out), "media": str(out / "media.jsonl"), **{k: summary[k] for k in
            ("files", "photos", "videos", "shots", "described_by_ai", "people", "trips", "places")}}


def _faces_for(shot: dict, faces: list | None) -> list[dict]:
    from . import people as ppl
    if not faces:
        return []
    if shot["kind"] == "video":
        t0, t1 = float(shot["t0"]), float(shot["t1"] or shot["t0"])
        faces = [f for f in faces if t0 <= float(f.get("t", -1)) < t1]
    out = []
    for f, (name, sim) in zip(faces, ppl.identify(faces)):
        row = {"box": [round(f["box"][0], 4), round(f["box"][1], 4), round(f["box"][0] + f["box"][2], 4),
                       round(f["box"][1] + f["box"][3], 4)], "size_px": f.get("px"), "name": name or None,
               "similarity": round(float(sim), 3) if name else None, "detector_score": f.get("score")}
        if "t" in f:
            row["t"] = f["t"]
        out.append(row)
    return out


def _best_moment(s: dict) -> float | None:
    if s["kind"] != "video":
        return None
    w = (s.get("ai") or {}).get("watch") or {}
    if w.get("peak") is not None and s["t0"] <= w["peak"] <= s["t1"]:
        return round(float(w["peak"]), 3)
    sm = s.get("samples") or {}
    t, sh, jit = sm.get("t") or [], sm.get("sharp") or [], sm.get("jitter") or []
    if not t:
        return round((s["t0"] + s["t1"]) / 2, 3)
    q = [math.log1p(a) - 40 * b for a, b in zip(sh, jit or [0] * len(sh))]
    return round(float(t[int(np.argmax(q))]), 3)


def build_record(r: dict, shots: list[dict], tech: dict, faces: list | None, trip: dict | None,
                 dup: dict[str, str]) -> dict:
    p = Path(r["path"])
    try:
        st = p.stat()
        size, mtime = st.st_size, datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds")
    except OSError:
        size, mtime = None, None
    w, h = r.get("w") or 0, r.get("h") or 0
    rows, names = [], Counter()
    for s in sorted(shots, key=lambda s: s["t0"]):
        a = s.get("ai") or {}
        k = f"{float(s['t0']):.3f}"
        fcs = _faces_for(s, faces)
        names.update(f["name"] for f in fcs if f["name"])
        described = int(a.get("v", 1)) >= 2 and a.get("source") not in ("heuristic", None)
        ai_block = {
            "source": a.get("source") or "heuristic", "version": int(a.get("v", 1)) if a.get("source") != "heuristic" else 0,
            "caption": a.get("caption") if described else None,
            "description": a.get("description") if described else None,
            "tags": a.get("tags") or [], "subjects": a.get("subjects") or (
                [{"label": (a.get("tags") or ["subject"])[0], "box": a["subject_box"]}] if a.get("subject_box") else []),
            "scene": a.get("scene") if described else None, "setting": a.get("setting") if described else None,
            "time_of_day": a.get("time_of_day") if described else None,
            "weather": a.get("weather") if described else None,
            "people": a.get("people") if described else None, "text": a.get("text") if described else None,
            "landmark": a.get("landmark") if described else None,
            "aesthetic": a.get("aesthetic") if described else None,
            "issues": a.get("issues") or [], "usable": bool(a.get("usable", True)),
        }
        if a.get("watch"):
            ai_block["watch"] = a["watch"]
        tch = dict(tech.get("shots", {}).get(k) or {})
        if s["kind"] == "video":
            m = s.get("metrics") or {}
            tch["camera_motion"] = {"label": motion_label(m), "pan": round(float(m.get("pan", 0)), 5),
                                    "shake": round(float(m.get("shake", 0)), 5),
                                    "activity": round(float(m.get("activity", 0)), 5)}
        key = lib.shot_key(s)
        rows.append({
            "id": key, "t0": float(s["t0"]), "t1": float(s["t1"]) if s.get("t1") is not None else None,
            "duration": float(s["dur"]) if s.get("dur") else None, "best_moment": _best_moment(s),
            "thumbnail": s.get("thumb"), "technical": tch, "ai": ai_block, "faces": fcs,
            "similar_group": dup.get(key),
            "uses": {"reel": {"score": a.get("score"), "role": a.get("role"), "mood": a.get("mood"),
                              "motion": a.get("motion"), "subject_x": a.get("subject_x"),
                              "subject_box": a.get("subject_box"), "note": a.get("note")}},
        })
    created = r.get("created")
    g = r.get("gps")
    return {
        "schema": SCHEMA_ID, "id": r["sig"], "path": str(p), "name": p.name, "kind": r["kind"],
        "file": {"size": size, "modified": mtime, "extension": p.suffix.lower().lstrip(".")},
        "media": {"width": w, "height": h, "orientation": "portrait" if h > w * 1.05 else (
                      "landscape" if w > h * 1.05 else "square"),
                  "aspect": round(w / h, 4) if h else None, "duration": r.get("duration"), "fps": r.get("fps"),
                  "hdr": bool(r.get("hdr")), "has_audio": r.get("has_audio"), "codec": r.get("codec"),
                  "equirect": bool(r.get("equirect"))},
        "captured": {"time": created, "day": str(created)[:10] if created else None,
                     "source": r.get("created_from") or ("metadata" if created else None)},
        "camera": tech.get("camera") or {},
        "location": ({"lat": g[0], "lon": g[1], "place": r.get("place")} if g else None),
        "trip": trip,
        "people": {"faces": sum(len(x["faces"]) for x in rows), "names": sorted(names)},
        "shots": rows,
        "analyzed": {"at": datetime.now().isoformat(timespec="seconds"), "generator": GENERATOR,
                     "versions": {"shots": _shots_version(), "technical": TECH_VERSION, "ai": _ai_version()}},
    }


def _shots_version():
    from .shots import ANALYSIS_VERSION
    return ANALYSIS_VERSION


def _ai_version():
    from .ai import AI_VERSION
    return AI_VERSION


def make_summary(records: list[dict], inputs, backend, seconds: float) -> dict:
    shots = [s for r in records for s in r["shots"]]
    tags = Counter(t for s in shots for t in s["ai"]["tags"])
    trips = {}
    for r in records:
        if r["trip"]:
            t = trips.setdefault(r["trip"]["id"], {**r["trip"], "files": 0})
            t["files"] += 1
    return {
        "schema": SCHEMA_ID, "generator": GENERATOR, "created": datetime.now().isoformat(timespec="seconds"),
        "inputs": [str(p) for p in inputs], "backend": backend.name if backend else None,
        "seconds": round(seconds, 1), "files": len(records),
        "photos": sum(r["kind"] == "photo" for r in records), "videos": sum(r["kind"] == "video" for r in records),
        "shots": len(shots), "described_by_ai": sum(1 for s in shots if s["ai"]["caption"]),
        "with_gps": sum(1 for r in records if r["location"]),
        "people": dict(Counter(n for r in records for n in r["people"]["names"]).most_common()),
        "places": dict(Counter(r["location"]["place"] for r in records if r["location"] and r["location"]["place"])
                       .most_common(20)),
        "top_tags": dict(tags.most_common(30)), "trips": sorted(trips.values(), key=lambda t: t["from"]),
        "duplicates": len({s["similar_group"] for s in shots if s["similar_group"]}),
    }


# ================================================================== reading it back
def load(path: str | Path):
    """Iterate the records of an analysis (its folder, or a media.jsonl file)."""
    p = Path(path).expanduser()
    if p.is_dir():
        p = p / "media.jsonl"
    if not p.exists():
        raise ReelError(f"no analysis at {path}")
    with open(p) as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def latest() -> Path | None:
    """The most recent analysis folder."""
    if not OUT_ROOT.exists():
        return None
    dirs = [d for d in OUT_ROOT.iterdir() if (d / "media.jsonl").exists()]
    return max(dirs, key=lambda d: (d / "media.jsonl").stat().st_mtime) if dirs else None


def compact(r: dict) -> dict:
    """A short view of a record (for agents and quick listings)."""
    return {"id": r["id"], "path": r["path"], "kind": r["kind"], "day": r["captured"]["day"],
            "place": (r.get("location") or {}).get("place"), "people": r["people"]["names"],
            "orientation": r["media"]["orientation"], "duration": r["media"]["duration"],
            "shots": [{"id": s["id"], "t0": s["t0"], "caption": s["ai"]["caption"], "tags": s["ai"]["tags"][:8],
                       "scene": s["ai"]["scene"], "aesthetic": s["ai"]["aesthetic"],
                       "sharpness": s["technical"].get("sharpness_label"), "best_moment": s["best_moment"],
                       "faces": len(s["faces"]), "similar_group": s["similar_group"]} for s in r["shots"]]}


def query(source: str | Path | None = None, text: str | None = None, tags: list[str] | None = None,
          people: list[str] | None = None, kind: str | None = None, min_aesthetic: float | None = None,
          sharp_only: bool = False, scene: str | None = None, day: str | None = None, limit: int = 100) -> list[dict]:
    """Records matching every filter given. text searches captions, descriptions, tags, place and landmark."""
    src = source or latest()
    if not src:
        raise ReelError("no analysis yet: run `tripshots analyze <folders>`")
    words = [re.sub(r"(es|s)$", "", w) if len(w) > 3 else w for w in (text or "").lower().split() if w]
    want_tags = {t.lower() for t in tags or []}
    want_people = set()
    if people:
        from .people import canonical
        want_people = {canonical(p) for p in people}
    out = []
    for r in load(src):
        if kind and r["kind"] != kind or day and r["captured"]["day"] != day:
            continue
        if want_people and not want_people <= set(r["people"]["names"]):
            continue
        ok_shots = []
        for s in r["shots"]:
            a = s["ai"]
            hay = " ".join([a.get("caption") or "", a.get("description") or "", " ".join(a["tags"]),
                            a.get("landmark") or "", (r.get("location") or {}).get("place") or ""]).lower()
            if words and not all(re.search(rf"\b{re.escape(w)}(s|es)?\b", hay) for w in words):
                continue  # whole words (plurals allowed): "cat" must not match "scattered"
            if want_tags and not want_tags <= set(a["tags"]):
                continue
            if scene and a.get("scene") != scene:
                continue
            if min_aesthetic is not None and (a.get("aesthetic") or 0) < min_aesthetic:
                continue
            if sharp_only and s["technical"].get("sharpness_label") != "sharp":
                continue
            ok_shots.append(s)
        if ok_shots:
            out.append({**r, "shots": ok_shots})
            if len(out) >= limit:
                break
    return out
