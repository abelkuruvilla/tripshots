"""Reel formats: shapes viewers recognise, each with its own text and order.

  montage  the default: a hook line, the story arc, a looping ending
  pov      "POV: …" sets up a feeling over the opening; good with dialogue or voice-over sounds
  list     "3 places in Utah you can't skip": numbered place cards, the best place saved for the payoff
           (built for sends and saves; needs footage from at least 3 places)
  series   "Day 4 of our West Coast road trip": a recognisable stem for a run of reels
  reveal   a tease first ("Wait for the last one"), the best shot held back for the payoff

`choose` picks one for "auto" from the footage and the sound; `apply` adds the format's text to a plan.
"""
from __future__ import annotations

from datetime import date

FORMATS = ("montage", "pov", "list", "series", "reveal")


def _day(s: dict) -> date | None:
    c = s.get("created")
    try:
        return date.fromisoformat(str(c)[:10]) if c else None
    except ValueError:
        return None


def trip_day(chosen: list[dict], all_shots: list[dict]) -> tuple[int | None, int]:
    """(day number of the chosen footage within the trip, days in the trip)."""
    days = sorted({d for d in (_day(s) for s in all_shots) if d})
    mine = [d for d in (_day(s) for s in chosen) if d]
    if not days or not mine:
        return None, 0
    main = max(set(mine), key=mine.count)
    return (main - days[0]).days + 1, (days[-1] - days[0]).days + 1


def choose(want: str, shots: list[dict], places: dict, words: dict | None, prefs: dict | None = None) -> str:
    """The format for a reel. want: a format, or auto."""
    if want in FORMATS:
        return want
    distinct = {p.split(",")[0].strip() for p in places.values() if p}
    if prefs and prefs.get("format") in FORMATS and prefs.get("confident"):
        f = prefs["format"]
        if f != "list" or len(distinct) >= 3:
            return f
    if words and words.get("kind") == "dialogue":
        return "pov"
    if len(distinct) >= 3:
        return "list"
    return "montage"


def short_place(p: str | None) -> str:
    return (p or "").split(",")[0].strip()


def list_order(pool: list[dict], places: dict) -> list[dict]:
    """Shots grouped by place, places in rising order of their best shot (the best place comes last)."""
    groups: dict[str, list[dict]] = {}
    for s in pool:
        groups.setdefault(short_place(places.get(s["id"])) or "?", []).append(s)
    order = sorted(groups, key=lambda g: max(float(x.get("ai", {}).get("score", 5)) for x in groups[g]))
    return [s for g in order for s in sorted(groups[g], key=lambda x: x.get("created") or "")]


def apply(plan: dict, fmt: str, by_id: dict, places: dict, copy: dict, hook_seg_end: float | None = None) -> None:
    """Add the format's on-screen text to a plan (after the hook, which the pipeline places)."""
    plan.setdefault("story", {})["format"] = fmt
    segs = plan["segments"]
    if fmt == "list":
        n = 0
        last = None
        for s in segs:
            if s.get("role") == "hook" or s.get("panel"):
                continue
            pl = short_place(places.get(s.get("shot_id")))
            if pl and pl != last and s["dur"] >= 0.7:
                n += 1
                plan["overlays"].append({"type": "label", "text": f"{n} · {pl}", "start": round(s["out_start"] + 0.05, 3),
                                         "duration": round(min(s["dur"], 2.2) - 0.1, 3), "format": "list"})
                last = pl
        plan["story"]["places"] = n
    if fmt == "pov":
        for o in plan["overlays"]:
            if o["type"] == "hook" and hook_seg_end:
                o["duration"] = round(max(o["duration"], min(3.6, hook_seg_end + 1.2) - o["start"]), 3)
