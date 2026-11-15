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
Styles (name: what it is):
{styles}
Reference reels of the user's learned styles (id, style: its cut, shape and words). Using one as the sound makes the
reel follow that reel's cut and show its words:
{sounds}
Used by the user's recent reels (pick others unless the request asks for one of these): {recent}
Music files: {music}

Request: "{request}"

Answer with JSON only:
{{"find": {{"place": "specific real place name or null", "people": ["me", ...] or [],
           "date_from": "YYYY-MM-DD or null", "date_to": "YYYY-MM-DD or null",
           "kinds": "both|photo|video", "text": "folder words or null",
           "camera": "drone|phone|action|camera or null"}},
  "make": {{"style": "one of the styles or null", "duration": seconds or null,
           "hook": "opening text, max 7 words, or null", "music": "one of the music files or null",
           "reference": "a reference reel id like r5, or null"}},
  "summary": "one sentence: what you understood, and the style and sound you chose",
  "question": "ONE question for the user only if the request can't be resolved at all (e.g. an unknown person),
               else null. Never ask about style or music: choose them"}}
Rules: people ["me"] only when the user must be IN the shot ("pictures I'm in", "photos of me", "with me in
them"); "my trip" / "my days in X" / "my photos" alone means footage they shot, so no people filter.
"my days in X" / "my trip to X" -> place X (be specific: "Yellowstone National Park"), text null (the place
search already checks folder names; text is only for event names that aren't places, like "wedding"). Use trip dates for "last summer", "that weekend". Only people
from the known list can be searched; if the request needs someone not in it, ask. Prefer photos only when
the request says pictures/photos. "drone footage/shots/videos" -> camera "drone" (likewise phone, GoPro/action
camera, camera); never put the camera in text. "all my ..." means no date filter.
Style and sound: always choose both, never leave the reel silent. Prefer the user's learned styles (marked
"learned") over the built-in ones unless the request asks for a mood a built-in style fits better. With a learned
style, set reference to the reference reel whose cut suits the request and the footage (a long opening hold for
one spectacular drone clip, fast montages for many places, place labels for a trip across regions), and leave
music null; a music file only when the request names one or no reference reel exists."""


def music_files() -> dict[str, str]:
    """{file name: path} of the tracks in TRIPSHOTS_MUSIC (at most 40 per folder)."""
    out = {}
    for d in os.environ.get("TRIPSHOTS_MUSIC", "").split(os.pathsep):
        if d.strip():
            for p in [p for p in Path(d).expanduser().rglob("*")
                      if p.suffix.lower() in (".mp3", ".m4a", ".wav", ".aac", ".flac")][:40]:
                out.setdefault(p.name, str(p))
    return out


def style_menu() -> tuple[str, str]:
    """(styles, reference reels) as lines for the prompt: each style with what it is and whether the user learned it,
    and every reference reel of a learned style with its cut."""
    from .config import HOME, list_styles, load_style
    from .recipes import describe
    lines, refs = [], []
    for name, path in sorted(list_styles().items()):
        try:
            st = load_style(name)
        except Exception:
            continue
        learned = HOME in Path(path).parents
        desc = " ".join(str(st.get("description") or "").split())[:160]
        lines.append(f"- {name}{' (learned)' if learned else ''}: {desc}")
        for r in st.get("recipes") or []:
            if r.get("source"):
                refs.append(f"- {r['id']} ({name}): {describe(r)}")
    return "\n".join(lines), "\n".join(refs[:60])


def recent_references(n: int = 12) -> list[str]:
    """Reference reel ids whose sound the user's latest reels used (read from their plans)."""
    from . import history
    out = []
    for row in reversed(history.load()):
        plan = Path(str(row.get("out", "")).replace(".mp4", ".plan.json"))
        try:
            rid = (json.loads(plan.read_text()).get("recipe") or {}).get("id")
        except (OSError, ValueError):
            continue
        if rid and rid not in out:
            out.append(rid)
        if len(out) >= n:
            break
    return out


def reference_sound(style: str | None, ref: str | None, avoid: list[str]) -> str | None:
    """The link of a learned style's reference reel to use as the sound: the one asked for, else the first not used
    recently (so an Ask never makes a silent reel when the style has reference reels)."""
    from .config import load_style
    if not style:
        return None
    try:
        recs = [r for r in load_style(style).get("recipes") or [] if r.get("source")]
    except Exception:
        return None
    pick = next((r for r in recs if r["id"] == ref), None) or \
        next((r for r in recs if r["id"] not in avoid and not r.get("unread")), None) or (recs[0] if recs else None)
    return pick["source"] if pick else None


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
    styles, sounds = style_menu()
    prompt = PROMPT.format(today=date.today().isoformat(), people=ppl, trips=trips, styles=styles,
                           sounds=sounds or "(none)", recent=", ".join(recent_references()) or "(none)",
                           music="\n".join(music) or "(none)", request=request.replace('"', "'"))
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
    camera = (f.get("camera") or "").lower() or None
    # the reel is named after what was asked for: "drone-footage", "yellowstone-national-park", "me-and-mom"
    name = f.get("place") or (f"{camera} footage" if camera else None) or " ".join(f.get("people") or []) or \
        f.get("text") or "ask"
    sel = catalog.find(place=f.get("place"), people=f.get("people") or None, date_from=f.get("date_from"),
                       date_to=f.get("date_to"), kinds=f.get("kinds") or "both", text=f.get("text"),
                       camera=camera if camera in catalog.CAMERAS else None,
                       label="-".join(name.lower().split())[:40])
    if sel["count"] == 0:
        looked = [f"{f.get('camera')} footage" if f.get("camera") else None, f.get("place"),
                  " and ".join(f.get("people") or []) or None,
                  f"from {f.get('date_from')}" if f.get("date_from") else None,
                  f"to {f.get('date_to')}" if f.get("date_to") else None,
                  f"with \"{f.get('text')}\" in the name" if f.get("text") else None]
        what = ", ".join(x for x in looked if x) or "that"
        return {"understood": plan, "found": sel,
                "question": f"I found nothing for {what} in {sel['searched']} files. Which trip, place or dates?"}
    sel["sheet"] = str(catalog.contact_sheet(sel["selection"]))
    if find_only:
        return {"understood": plan, "found": sel}
    if sel["count"] < 5:
        log(f"only {sel['count']} files match: the reel will be short")
    m = plan.get("make") or {}
    paths, label = catalog.selection_paths(sel["selection"])
    pick = m.get("music")
    pick = music_files().get(Path(pick).name) if pick else None  # the AI answers with a file name
    sound = music or pick or reference_sound(m.get("style"), m.get("reference"), recent_references())
    if sound and not (music or pick):
        log(f"sound: reference reel {m.get('reference') or ''} of {m.get('style')}: {sound}")
    res = make_variants(1, paths, sound, m.get("style"), None, m.get("duration"),
                        backend_name, m.get("hook"), None, False, not render, workers=workers,
                        extras={"name": label})
    return {"understood": plan, "found": {k: sel[k] for k in ("selection", "count", "photos", "videos", "days",
                                                                 "people", "notes", "sheet")}, **res}
