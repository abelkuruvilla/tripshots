"""`tripshots ask "a reel about my days in Yellowstone"`: plain language -> search -> reel.

Uses the configured AI backend (your Claude subscription, MiniMax or the API) only to turn the request
into a search and edit settings; everything else is the normal pipeline. Agents that speak MCP don't
need this (they do the same through the MCP tools), but it gives the CLI and the app the same skill.
"""
from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

from .util import ReelError, log

PROMPT = """You turn a request for an Instagram Reel made from the user's own travel footage into a footage
search and edit settings. Today is {today}.

Known people (face recognition): {people}
Footage trips (date ranges, GPS centre, main folders):
{trips}
Styles: {styles}
Music files: {music}

Request: "{request}"

Answer with JSON only:
{{"find": {{"place": "specific real place name or null", "people": ["me", ...] or [],
           "date_from": "YYYY-MM-DD or null", "date_to": "YYYY-MM-DD or null",
           "kinds": "both|photo|video", "text": "folder words or null"}},
  "make": {{"style": "one of the styles or null", "duration": seconds or null,
           "hook": "opening text, max 7 words, or null", "music": "one of the music files or null"}},
  "summary": "one sentence: what you understood",
  "question": "ONE question for the user if the request can't be resolved (e.g. an unknown person), else null"}}
Rules: people ["me"] only when the user must be IN the shot ("pictures I'm in", "photos of me", "with me in
them"); "my trip" / "my days in X" / "my photos" alone means footage they shot, so no people filter.
"my days in X" / "my trip to X" -> place X (be specific: "Yellowstone National Park"), text null (the place
search already checks folder names; text is only for event names that aren't places, like "wedding"). Use trip dates for "last summer", "that weekend". Only people
from the known list can be searched; if the request needs someone not in it, ask. Prefer photos only when
the request says pictures/photos."""


def music_files() -> dict[str, str]:
    """{file name: path} of the tracks in TRIPSHOTS_MUSIC (at most 40 per folder)."""
    out = {}
    for d in os.environ.get("TRIPSHOTS_MUSIC", "").split(os.pathsep):
        if d.strip():
            for p in [p for p in Path(d).expanduser().rglob("*")
                      if p.suffix.lower() in (".mp3", ".m4a", ".wav", ".aac", ".flac")][:40]:
                out.setdefault(p.name, str(p))
    return out


def interpret(request: str, backend) -> dict:
    from . import catalog, people
    from .ai import extract_json
    from .config import list_styles
    try:
        tr = catalog.trips(name=False)
        trips = "\n".join(f"- {t['from']}..{t['to']} ({t['days']} days, {t['files']} files) centre {t['centre']} "
                          f"folders {[Path(f).name for f in t['folders']]}" for t in tr[-25:]) or "(none)"
    except ReelError:
        trips = "(no footage folders set)"
    ppl = ", ".join(p["name"] + (f" ({', '.join(p['aliases'])})" if p["aliases"] else "")
                    for p in people.list_people()) or "(nobody yet)"
    music = music_files()  # only file names go to the AI, not paths
    prompt = PROMPT.format(today=date.today().isoformat(), people=ppl, trips=trips,
                           styles=", ".join(sorted(list_styles())), music="\n".join(music) or "(none)",
                           request=request.replace('"', "'"))
    out = extract_json(backend.ask(prompt, max_tokens=1200))
    if not isinstance(out, dict):
        raise ReelError("could not understand the request; try `tripshots find` + `tripshots make`")
    return out


def ask(request: str, backend_name: str | None = None, music: str | None = None, render: bool = False,
        workers: int = 2, find_only: bool = False) -> dict:
    from . import catalog
    from .ai import get_backend
    from .pipeline import make_variants
    backend = get_backend(backend_name)
    if backend is None:
        raise ReelError("`ask` needs an AI backend (claude CLI, MiniMax or API key); or use `tripshots find`")
    plan = interpret(request, backend)
    log(f"understood: {plan.get('summary', '')}")
    if plan.get("question"):
        return {"question": plan["question"], "understood": plan}
    f = plan.get("find") or {}
    sel = catalog.find(place=f.get("place"), people=f.get("people") or None, date_from=f.get("date_from"),
                       date_to=f.get("date_to"), kinds=f.get("kinds") or "both", text=f.get("text"))
    if sel["count"] == 0:
        return {"understood": plan, "found": sel, "question": "I found no footage for that; which trip or dates?"}
    sel["sheet"] = str(catalog.contact_sheet(sel["selection"]))
    if find_only:
        return {"understood": plan, "found": sel}
    if sel["count"] < 5:
        log(f"only {sel['count']} files match: the reel will be short")
    m = plan.get("make") or {}
    paths, label = catalog.selection_paths(sel["selection"])
    pick = m.get("music")
    pick = music_files().get(Path(pick).name) if pick else None  # the AI answers with a file name
    res = make_variants(1, paths, music or pick, m.get("style"), None, m.get("duration"),
                        backend_name, m.get("hook"), None, False, not render, workers=workers,
                        extras={"name": label})
    return {"understood": plan, "found": {k: sel[k] for k in ("selection", "count", "photos", "videos", "days",
                                                                 "people", "notes", "sheet")}, **res}
