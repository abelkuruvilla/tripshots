"""What your earlier reels already showed, so a series cut from the same footage doesn't repeat itself.

Every finished render is noted in ~/.tripshots/history.json: which stretch of which file each slot showed, and
whether it carried the reel (the opening, the payoff, the ending). When the next reel is planned from the same
footage, `shown` turns that into a mark-down per shot: the shot itself, the same moment from the same clip or
taken a minute apart, and (for the opening and the ending only) the same stop of the trip. It is a mark-down,
never a filter: the best shot of a small trip can come back, an earlier opening only when nothing else carries
one. A reel whose file is gone is forgotten, and a reel being made again never counts against itself.

Style key `shots.fresh` (1 = as described, 0 = off), `make --fresh on|off`.
"""
from __future__ import annotations

import bisect
from datetime import datetime
from pathlib import Path

from .config import HOME
from .util import log, read_json, write_json

STORE = HOME / "history.json"
KEEP = 60          # reels remembered
LOOK_BACK = 12     # earlier reels of the same footage that count
LEAD_ROLES = ("hook", "peak", "ending")
LEAD, BODY, SAME_MOMENT, CAP = 1.0, 0.5, 0.7, 2.0


def load() -> list[dict]:
    rows = read_json(STORE, []) or []
    return [r for r in rows if isinstance(r, dict) and r.get("out") and isinstance(r.get("uses"), list)]


def _key(path) -> str:
    try:
        return str(Path(path).expanduser().resolve())
    except OSError:
        return str(path)


def _uses(plan: dict) -> list[dict]:
    segs = plan.get("segments") or []
    out = []
    for i, sg in enumerate(segs):
        lead = sg.get("role") in LEAD_ROLES or bool(sg.get("hold")) or i in (0, len(segs) - 1)
        for c in (sg.get("clips") if sg.get("panel") else [sg]) or []:
            if not c.get("src"):
                continue
            t0 = float(c.get("in") or 0.0)
            length = float(c["t1"] - c["t0"]) if sg.get("panel") else float(sg.get("dur") or 0.0)
            photo = c.get("kind") == "photo"
            out.append({"src": str(c["src"]), "t0": round(t0, 2),
                        "t1": round(t0 if photo else t0 + length * float(c.get("speed") or 1.0), 2),
                        "lead": bool(lead and not sg.get("panel"))})
    return out


def record(plan: dict, out: Path) -> None:
    """Note what the reel at `out` shows (replaces what an earlier render of the same file showed)."""
    uses = _uses(plan)
    if not uses:
        return
    key = _key(out)
    rows = [r for r in load() if _key(r["out"]) != key]
    rows.append({"out": key, "at": datetime.now().isoformat(timespec="seconds"), "style": plan.get("style"),
                 "uses": uses})
    STORE.parent.mkdir(parents=True, exist_ok=True)
    write_json(STORE, rows[-KEEP:])


def remember(plan: dict, out: Path) -> None:
    """`record` for the render path: remembering a reel never fails its render."""
    try:
        record(plan, out)
    except Exception as e:
        log(f"this reel was not noted for the next one ({str(e)[:80]})")


def shown(shots: list[dict], skip: list | tuple = (), places: dict | None = None) -> dict:
    """What earlier reels showed of `shots`: {"shot": {id: weight}, "place": {place key: earlier leads},
    "where": places, "reels": [file names], "n": shots shown as they are}. `skip`: outputs that don't count
    (the reel being made, its variants). `places`: diversity.place_keys(shots), to mark the stops earlier reels
    opened or ended on."""
    from .diversity import _when, same_scene
    skipped = {_key(p) for p in skip if p}
    by_src: dict[str, list[dict]] = {}
    for s in shots:
        by_src.setdefault(str(s.get("src")), []).append(s)
    rows = []
    for r in reversed(load()):
        if _key(r["out"]) in skipped or not Path(r["out"]).exists():
            continue
        if any(str(u.get("src")) in by_src for u in r["uses"]):
            rows.append(r)
        if len(rows) >= LOOK_BACK:
            break
    weight: dict[str, float] = {}
    direct: dict[str, float] = {}
    lead_place: dict[str, int] = {}
    timed = sorted(((t, s["id"]) for s in shots if (t := _when(s)) is not None))
    times = [t for t, _ in timed]
    by_id = {s["id"]: s for s in shots}

    def near(s: dict) -> list[dict]:  # the same moment: the clip around it, pictures taken minutes apart
        out = [c for c in by_src.get(str(s.get("src")), []) if c["id"] != s["id"]]
        t = _when(s)
        if t is not None:
            a, b = bisect.bisect_left(times, t - 600), bisect.bisect_right(times, t + 600)
            out += [by_id[i] for _, i in timed[a:b] if i != s["id"] and by_id[i].get("src") != s.get("src")]
        return out

    for r in rows:
        mine: dict[str, float] = {}
        for u in r["uses"]:
            w = LEAD if u.get("lead") else BODY
            t0, t1 = float(u.get("t0") or 0), float(u.get("t1") or 0)
            for s in by_src.get(str(u.get("src")), []):
                if s.get("kind") == "video" and not (float(s.get("t0") or 0) < t1 - 0.2
                                                      and float(s.get("t1") or 0) > t0 + 0.2):
                    continue
                mine[s["id"]] = max(mine.get(s["id"], 0.0), w)
        for sid, w in list(mine.items()):
            direct[sid] = direct.get(sid, 0.0) + w
            if w >= LEAD and places:
                k = places.get(sid, sid)
                lead_place[k] = lead_place.get(k, 0) + 1
        spread: dict[str, float] = {}
        for sid, w in mine.items():
            for c in near(by_id[sid]):
                if c["id"] not in mine and spread.get(c["id"], 0.0) < w * SAME_MOMENT and same_scene(by_id[sid], c):
                    spread[c["id"]] = w * SAME_MOMENT
        for sid, w in {**spread, **mine}.items():
            weight[sid] = min(CAP, weight.get(sid, 0.0) + w)
    return {"shot": weight, "place": lead_place, "where": places or {},
            "reels": [Path(r["out"]).name for r in rows], "n": len(direct)}


def mark_down(style: dict, shot: dict, lead: bool = False) -> float:
    """How much an earlier showing counts against `shot` (0 = never shown, or `shots.fresh` is off): 0.5 per
    reel it was in, 1 per reel it opened, peaked or ended. `lead`: for a slot that carries the reel, where the
    stop an earlier reel opened or ended on counts too."""
    seen = style.get("_shown")
    fresh = float((style.get("shots") or {}).get("fresh", 1.0) or 0)
    if not seen or fresh <= 0:
        return 0.0
    w = float(seen["shot"].get(shot["id"], 0.0))
    if lead:
        w += 0.3 * min(3, int(seen["place"].get(seen["where"].get(shot["id"], shot["id"]), 0)))
    return fresh * w
