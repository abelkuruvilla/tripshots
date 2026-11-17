"""Choosing a shot by hand in the editor: every shot of the reel's footage (not only the best), and which part of a
long clip plays in a slot (dragged by the user, or chosen by the AI from frames across the whole clip).

A shot is a window [t0, t1] of a file; a long file is cut into several shots. The part that plays may lie anywhere
in the file, so the window here runs over the whole file, not just the shot."""
from __future__ import annotations

import subprocess
from pathlib import Path

from .config import CACHE_ROOT
from .util import ReelError, ffmpeg_base, log, read_json

PROXIES = CACHE_ROOT / "proxies"


def _shots(plan: dict) -> dict:
    work = Path(plan.get("work") or ".")
    return {s["id"]: s for s in (read_json(work / "shots_scored.json", []) or [])}


def file_length(shots: dict, shot: dict) -> float:
    """The whole file's length: the end of its last shot."""
    return max([float(s.get("t1") or 0) for s in shots.values() if s.get("src") == shot.get("src")]
               + [float(shot.get("t1") or 0)])


def _item(s: dict, used: set, lens: dict) -> dict:
    from .insight import burned_in
    from .planner import _quality
    a = s.get("ai", {})
    return {"id": s["id"], "used": s["id"] in used, "kind": s["kind"], "score": round(_quality(s), 1),
            "len_s": round(s["t1"] - s["t0"], 1) if s["kind"] == "video" else None,
            "file_s": round(lens.get(s["src"], 0), 1) if s["kind"] == "video" else None,
            "t0": s.get("t0"), "file": Path(s["src"]).name, "when": (s.get("created") or "")[:16],
            "note": a.get("note", ""), "tags": a.get("tags", [])[:5], "thumb": s.get("thumb"),
            "caption": a.get("caption", ""), "vibes": list((a.get("vibes") or {}))[:2], "size": a.get("shot_size"),
            "angle": a.get("angle"), "words": burned_in(s) >= 0.5}


def _words(s: dict) -> str:
    a = s.get("ai", {})
    return " ".join(str(x) for x in [a.get("caption"), a.get("note"), a.get("description"), Path(s["src"]).name,
                                     a.get("landmark"), a.get("scene"), a.get("setting"), a.get("time_of_day"),
                                     a.get("shot_size"), a.get("angle"), *(a.get("tags") or []),
                                     *(a.get("subjects") or []), *list(a.get("vibes") or {}), s.get("place")]
                    if x).lower()


def browse(plan_path: Path, q: str = "", kind: str = "all", sort: str = "best", offset: int = 0,
           limit: int = 60, group: bool = True) -> dict:
    """Every shot of the reel's footage, filtered by words and kind, best first or in the order filmed. `group`: one
    card per file (its best matching shot), since the part that plays can then be chosen anywhere in the file."""
    from .planner import _quality
    plan = read_json(plan_path)
    shots = _shots(plan)
    used = {s.get("shot_id") for s in plan["segments"]} | {c.get("shot_id") for s in plan["segments"]
                                                          for c in s.get("clips") or []}
    lens: dict[str, float] = {}
    for s in shots.values():
        if s.get("kind") == "video":
            lens[s["src"]] = max(lens.get(s["src"], 0.0), float(s.get("t1") or 0))
    pick = [s for s in shots.values() if kind in ("all", "", None) or s.get("kind") == kind]
    words = [w for w in (q or "").lower().split() if w]
    if words:
        pick = [s for s in pick if all(w in _words(s) for w in words)]
    if group:
        best: dict[str, dict] = {}
        for s in pick:
            b = best.get(s["src"])
            if b is None or _quality(s) > _quality(b):
                best[s["src"]] = s
        pick = list(best.values())
    if sort == "time":
        pick.sort(key=lambda s: (s.get("created") or "", s["src"], float(s.get("t0") or 0)))
    elif sort == "file":
        pick.sort(key=lambda s: (Path(s["src"]).name, float(s.get("t0") or 0)))
    else:
        pick.sort(key=lambda s: -_quality(s))
    offset, limit = max(0, int(offset)), max(1, min(200, int(limit)))
    return {"total": len(pick), "offset": offset,
            "items": [_item(s, used, lens) for s in pick[offset:offset + limit]]}


def _need(plan: dict, shot: dict, slot: int | None, dur: float | None) -> tuple[float, float]:
    """(seconds of footage the slot plays, speed) for this shot in that slot, as a swap would set it."""
    from .config import load_style
    from .planner import _shot_fields
    segs = plan["segments"]
    if slot is not None and 1 <= slot <= len(segs):
        d, level = float(segs[slot - 1]["dur"]), segs[slot - 1].get("level", "mid")
    else:
        d, level = float(dur or 1.5), "mid"
    e, _ = _shot_fields(shot, d, level, load_style(plan.get("style")), 0)
    speed = float(e.get("speed", 1.0))
    return round(d * speed, 3), speed


def window(plan_path: Path, shot_id: str, at: float, need: float) -> Path:
    """The chosen part of the clip as a small file the app's player can always play (4K60, 10-bit and HDR files
    often can't be played directly, and a copy of a whole long clip takes minutes). About a second to make."""
    from .fx import hdr_chain
    from .util import short_hash
    sh = _shots(read_json(plan_path)).get(shot_id)
    if not sh or sh.get("kind") != "video":
        raise ReelError(f"unknown clip {shot_id}")
    at, need = max(0.0, float(at)), max(0.1, min(30.0, float(need)))
    key = f"{sh['src']}|{at:.2f}|{need:.2f}"
    dst = PROXIES / f"win_{short_hash(key, 16)}.mp4"
    if dst.exists():
        return dst
    PROXIES.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.stem + ".part.mp4")
    vf = ",".join(["scale=-2:480"] + hdr_chain(sh) + ["format=yuv420p"])
    try:
        subprocess.run(ffmpeg_base() + ["-ss", f"{at:.3f}", "-i", sh["src"], "-t", f"{need:.3f}", "-vf", vf,
                                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "24", "-an",
                                        "-movflags", "+faststart", str(tmp)],
                       check=True, capture_output=True, timeout=120)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        tmp.unlink(missing_ok=True)
        raise ReelError(f"couldn't read {Path(sh['src']).name} to show it ({type(e).__name__})") from None
    tmp.replace(dst)
    return dst


def filmstrip(sh: dict, length: float, n: int = 14) -> Path | None:
    """n frames evenly across the whole clip, side by side: the picture under the trim bar."""
    from concurrent.futures import ThreadPoolExecutor
    import numpy as np
    from PIL import Image
    from .insight import frame_at
    from .util import short_hash
    key = f"{sh['src']}|{length:.2f}|{n}"
    out = PROXIES / f"strip_{short_hash(key, 16)}.jpg"
    if out.exists():
        return out
    ts = [length * (k + 0.5) / n for k in range(n)]
    with ThreadPoolExecutor(6) as pool:   # one seek each; the drive answers several at once
        frames = list(pool.map(lambda t: frame_at(sh["src"], t, 160, sh), ts))
    ok = [f for f in frames if f is not None]
    if not ok:
        return None
    h, w = ok[0].shape[:2]
    strip = Image.new("RGB", (w * n, h), (24, 24, 24))
    for k, f in enumerate(frames):
        if f is not None:
            strip.paste(Image.fromarray(np.asarray(f)).resize((w, h)), (k * w, 0))
    PROXIES.mkdir(parents=True, exist_ok=True)
    strip.save(out, "JPEG", quality=80)
    return out


def clip(plan_path: Path, shot_id: str, slot: int | None = None, dur: float | None = None) -> dict:
    """What the trim step needs: the whole clip's length, how much of it the slot plays, a strip of frames across
    it, and where TripShots would start (the shot's best moment). The chosen part plays from window()."""
    from .planner import _best_window
    plan = read_json(plan_path)
    shots = _shots(plan)
    sh = shots.get(shot_id)
    if not sh:
        raise ReelError(f"unknown shot {shot_id}")
    if sh.get("kind") != "video":
        return {"kind": "photo"}
    need, speed = _need(plan, sh, slot, dur)
    length = file_length(shots, sh)
    best = _best_window(sh, need) if float(sh["t1"]) - float(sh["t0"]) >= need else \
        max(0.0, min(length - need, float(sh["t0"]) - (need - (float(sh["t1"]) - float(sh["t0"]))) / 2))
    strip = filmstrip(sh, length)
    peak = ((sh.get("ai") or {}).get("watch") or {}).get("peak")
    return {"kind": "video", "id": shot_id, "file": Path(sh["src"]).name, "length": round(length, 3),
            "need": need, "speed": speed, "t0": sh["t0"], "t1": sh["t1"], "best_in": round(best, 3),
            "peak": peak, "strip": str(strip) if strip else None}


AI_PROMPT = """You are editing an Instagram Reel from travel footage. One slot of the reel is {need:.2f} s long and will
play part of a {length:.1f} s clip. The sheet shows the clip's frames in order, each labelled with its time in
seconds.

This slot: {role}. The shot before it shows: {before}. The shot after it shows: {after}.
{peak}
Choose where the slot should start so that its {need:.2f} s hold the best moment of the clip for this place in the
reel: the action or the view at its best, sharp and steady, not the camera starting or stopping, nobody walking out
of frame, no fumbling. Keep the moment a little past the middle of the window.

Answer with JSON only: {{"start": seconds, "why": "one short plain sentence a non-editor understands"}}"""


def _sheet(sh: dict, length: float, n: int = 12) -> tuple[Path, list[float]]:
    """A contact sheet of n frames across the whole file, each labelled with its time (for the AI)."""
    import numpy as np
    from PIL import Image, ImageDraw
    from .insight import STRIPS, frame_at
    from .util import short_hash
    ts = [round(length * (k + 0.5) / n, 2) for k in range(n)]
    key = f"{sh['src']}|{length:.2f}|{n}"
    out = STRIPS / f"sheet_{short_hash(key, 16)}.jpg"
    if out.exists():
        return out, ts
    frames = [frame_at(sh["src"], t, 320, sh) for t in ts]
    ok = [f for f in frames if f is not None]
    if not ok:
        raise ReelError(f"couldn't read frames of {Path(sh['src']).name}")
    h, w = ok[0].shape[:2]
    cols = 4 if w >= h else 6
    rows = (n + cols - 1) // cols
    sheet = Image.new("RGB", (cols * w, rows * (h + 28)), (20, 20, 20))
    d = ImageDraw.Draw(sheet)
    for k, (t, f) in enumerate(zip(ts, frames)):
        x, y = (k % cols) * w, (k // cols) * (h + 28)
        if f is not None:
            sheet.paste(Image.fromarray(np.asarray(f)).resize((w, h)), (x, y + 28))
        d.text((x + 6, y + 6), f"{t:.1f}s", fill=(255, 214, 0))
    STRIPS.mkdir(parents=True, exist_ok=True)
    sheet.save(out, "JPEG", quality=85)
    return out, ts


def ai_window(plan_path: Path, shot_id: str, slot: int | None = None, dur: float | None = None,
              backend_name: str | None = None) -> dict:
    """Let the AI choose which part of the clip plays in the slot. Without an AI: TripShots' own pick (the
    sharpest, steadiest stretch, or the moment Gemini saw)."""
    from .ai import extract_json, get_backend
    info = clip(plan_path, shot_id, slot, dur)
    if info.get("kind") != "video":
        return {"in": None, "by": "none", "why": "a photo has no part to choose"}
    plan = read_json(plan_path)
    shots = _shots(plan)
    sh = shots[shot_id]
    need, length = info["need"], info["length"]
    hi = max(0.0, length - need)
    if hi <= 0.05:
        return {"in": 0.0, "by": "rules", "why": "the clip is about as long as the slot: it plays whole"}
    backend = get_backend(backend_name)
    if backend is None:
        return {"in": info["best_in"], "by": "rules", "why": "the sharpest, steadiest stretch (no AI is set up)"}
    segs = plan["segments"]

    def told(i: int) -> str:
        if not 0 <= i < len(segs):
            return "nothing (the reel " + ("starts" if i < 0 else "ends") + " here)"
        s = shots.get(segs[i].get("shot_id")) or {}
        return (s.get("ai") or {}).get("caption") or segs[i].get("note") or "another shot of the trip"
    if slot:
        seg = segs[slot - 1]
        role = f"shot {slot} of {len(segs)}, role {seg.get('role') or 'middle'}, music {seg.get('level', 'mid')}"
        before, after = told(slot - 2), told(slot)
    else:
        role, before, after = "a new shot in the reel", "-", "-"
    pk = info.get("peak")
    peak = f"A video model that watched the clip thought its best instant is at {pk:.1f} s.\n" if pk is not None else ""
    img, _ = _sheet(sh, length)
    prompt = AI_PROMPT.format(need=need, length=length, role=role, before=before, after=after, peak=peak)
    try:
        data = extract_json(backend.ask(prompt, [img], max_tokens=400)) or {}
        start = float(data.get("start"))
    except Exception as e:  # the user still gets a sensible part
        log(f"clip window: the AI's answer couldn't be used ({e}); TripShots' own pick instead")
        return {"in": info["best_in"], "by": "rules", "why": "the sharpest, steadiest stretch (the AI didn't answer)"}
    start = max(0.0, min(hi, start))
    # the sheet has a frame every length/12 s: within the stretch the AI chose, settle on its sharpest, steadiest part
    gap = length / 12
    if gap > 2 * need:
        from .planner import _best_window
        near = [x for x in shots.values() if x.get("src") == sh["src"] and x.get("kind") == "video"
                and float(x["t0"]) <= start + need / 2 <= float(x["t1"]) and float(x["t1"]) - float(x["t0"]) >= need]
        if near:
            fine = _best_window(near[0], need)
            if abs(fine - start) <= gap / 2:
                start = max(0.0, min(hi, fine))
    return {"in": round(start, 3), "by": backend.name, "why": str(data.get("why") or "").strip()[:200]}
