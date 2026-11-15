"""Copy for posting a reel: a caption written for reach, hashtags, search keywords and alt text.

What Instagram rewards (as it describes its own ranking, and what reels that travel well have in common):
- shares ("sends") are the strongest signal for reach to people who don't follow you, then saves, then
  watch time and comments; likes count least. The caption asks for one of these, plainly and once.
- Instagram search reads the caption: the place names and what the reel is about, in plain words, near the
  start, find people searching for them. Keywords beat a wall of hashtags.
- at most 5 hashtags per post (Instagram's own limit), specific ones: the place, the niche, one broader tag.
- the first line shows before "more" (about 125 characters): it carries the hook.
- alt text describes the reel for screen readers and also helps it be understood.

`write(plan_path)` writes NAME.caption.txt (caption + hashtags, ready to paste) and NAME.social.json.
"""
from __future__ import annotations

import re
from pathlib import Path

from .util import ReelError, log, read_json, write_json

MAX_TAGS = 5
FIRST_LINE = 125


def _facts(plan: dict) -> dict:
    """What the reel shows, from the plan and the shots' AI notes: places, subjects, notes, length, sound."""
    from .planedit import _shots
    by_id = _shots(plan)
    places, subjects, notes, landmarks = [], [], [], []
    for o in plan.get("overlays") or []:
        if o.get("type") in ("location", "label"):
            places.append(" ".join(x for x in (o.get("main"), o.get("sub")) if x) or o.get("text") or "")
    try:
        from .pipeline import _seg_facts
        for f in _seg_facts(plan, by_id, list(by_id.values()), full=True):
            places += [f[k] for k in ("place", "region") if f.get(k)]
            if f.get("landmark"):
                landmarks.append(f["landmark"])
    except Exception as e:  # places are a bonus: offline or no positions is fine
        log(f"caption: places not looked up ({str(e)[:60]})")
    for s in plan["segments"]:
        a = (by_id.get(s.get("shot_id")) or {}).get("ai") or {}
        subjects += a.get("tags") or []
        if a.get("note"):
            notes.append(a["note"])
    words = [o.get("text") for o in plan.get("overlays") or []
             if o.get("type") in ("hook", "cta", "text") and o.get("text")]
    uniq = lambda xs: [x for x in dict.fromkeys(x.strip() for x in xs if x and x.strip())]
    return {"places": uniq(landmarks + places)[:8], "subjects": uniq(subjects)[:16], "notes": uniq(notes)[:8],
            "on_screen": uniq(words)[:6], "seconds": round(sum(float(s["dur"]) for s in plan["segments"]), 1),
            "sound": (plan.get("music") or {}).get("label"), "format": (plan.get("story") or {}).get("format")}


PROMPT = """You write the Instagram post for a travel Reel ({seconds}s, {fmt}). The goal is reach: people who
don't follow the account should find it, watch it to the end, and send it to someone or save it.

What the reel shows (use only these facts; never invent a place, a date, a number or an experience):
- places: {places}
- subjects: {subjects}
- shot notes: {notes}
- words on screen: {on_screen}
- sound: {sound}
Voice: {tone}{extra}

How Instagram ranks reels: sends (shares in DMs) matter most for reaching non-followers, then saves, then watch
time and comments. Its search reads captions, so plain keywords (the place names, the activity, the kind of trip)
help people find the reel. Instagram allows at most 5 hashtags.

Return ONLY JSON:
{{"caption": "...", "hashtags": ["..."], "keywords": ["..."], "alt_text": "...", "first_comment": "...",
  "on_screen_keywords": "...", "alternatives": ["...", "..."], "why": "..."}}
- caption: 2-5 short lines. Line 1 is the hook, under {first} characters, and makes someone stop (curiosity, a
  POV, a specific promise); it names the main place when one is known. Then 1-3 lines that work in 2-3 search
  keywords naturally (place + what you do/see there + the kind of trip). Last line asks for ONE action that
  fits the reel: send it to the person you'd go with, or save it for a trip, or a question that is easy to
  answer in the comments. No hashtags inside the caption, no clichés ("wanderlust", "vibes", "take me back"),
  at most 2 emojis.
- hashtags: 3 to 5, without #, most specific first: the place, the region or park, the niche (e.g.
  roadtripusa, droneshots), at most one broad tag. No #fyp/#explore/#viral, no banned or spammy tags.
- keywords: 5-8 search phrases people actually type (e.g. "yellowstone itinerary", "big sur drive").
- alt_text: one plain sentence describing what is seen, for screen readers (max 200 characters).
- first_comment: optional extra line to pin as the first comment (a detail, a tip or a question), or "".
- on_screen_keywords: a short line (max 6 words) with the main keyword, to show in the first second on screen.
- alternatives: two other first lines with a different angle.
- why: one sentence on the angle you chose."""


def _clean_tag(t: str) -> str:
    return re.sub(r"[^\w]", "", str(t).lstrip("#"), flags=re.UNICODE)


def _local(f: dict) -> dict:
    """Without an AI: an honest caption built from the places and subjects."""
    place = f["places"][0].split(",")[0] if f["places"] else ""
    subj = ", ".join(f["subjects"][:3])
    first = (f"{place}, like you've never seen it" if place else "Save this for your next trip")[:FIRST_LINE]
    body = f"{place + ': ' if place else ''}{subj}." if subj else ""
    tags = [_clean_tag(p.split(",")[0]).lower() for p in f["places"][:3]] + ["travelreels"]
    tags = [t for t in dict.fromkeys(tags) if t][:MAX_TAGS]
    kws = [p.split(",")[0].lower() for p in f["places"][:3]] + [f"{s} travel" for s in f["subjects"][:3]]
    return {"caption": "\n".join(x for x in (first, body, "Send this to who you'd go with.") if x),
            "hashtags": tags, "keywords": [k for k in dict.fromkeys(kws) if k][:8],
            "alt_text": (f"Travel reel of {place}: " if place else "Travel reel: ") + (subj or "landscapes"),
            "first_comment": "", "on_screen_keywords": place, "alternatives": [], "why": "written without an AI",
            "source": "local"}


def generate(plan: dict, tone: str | None = None, extra: str | None = None, backend=None) -> dict:
    f = _facts(plan)
    from .ai import extract_json, get_backend
    from .config import load_style
    try:
        backend = backend or get_backend(None)
    except Exception as e:
        log(f"caption: no AI ({str(e)[:80]}); writing one from the places and subjects")
        backend = None
    if backend is None:
        return _local(f)
    style = load_style(plan.get("style")) if plan.get("style") else {}
    prompt = PROMPT.format(seconds=f["seconds"], fmt=f["format"] or "montage", places=", ".join(f["places"]) or "unknown",
                           subjects=", ".join(f["subjects"]) or "landscapes", notes="; ".join(f["notes"]) or "-",
                           on_screen=" / ".join(f["on_screen"]) or "-", sound=f["sound"] or "-",
                           tone=tone or (style.get("caption") or {}).get("tone") or "warm, concise, first-person",
                           extra=f"\nAlso: {extra}" if extra else "", first=FIRST_LINE)
    try:
        data = extract_json(backend.ask(prompt, None, max_tokens=1200)) or {}
    except Exception as e:
        log(f"caption: the AI didn't answer ({str(e)[:80]}); writing one from the places and subjects")
        return _local(f)
    tags = [t for t in dict.fromkeys(_clean_tag(h) for h in data.get("hashtags") or []) if t][:MAX_TAGS]
    cap = str(data.get("caption") or "").strip()
    cap = "\n".join(re.sub(r"(?<!\w)#\w+", "", ln).rstrip() for ln in cap.splitlines()).strip()  # tags go below
    if not cap:
        return _local(f)
    return {"caption": cap, "hashtags": tags,
            "keywords": [str(k).strip() for k in data.get("keywords") or [] if str(k).strip()][:8],
            "alt_text": str(data.get("alt_text") or "").strip()[:240],
            "first_comment": str(data.get("first_comment") or "").strip(),
            "on_screen_keywords": str(data.get("on_screen_keywords") or "").strip(),
            "alternatives": [str(a).strip() for a in data.get("alternatives") or [] if str(a).strip()][:3],
            "why": str(data.get("why") or "").strip(), "source": getattr(backend, "name", "ai")}


def post_text(s: dict) -> str:
    """The caption as it's pasted: the words, a blank line, the hashtags."""
    return (s.get("caption", "") + "\n\n" + " ".join("#" + h for h in s.get("hashtags") or [])).strip() + "\n"


def checks(s: dict) -> list[str]:
    """What could hold the post back, in plain words."""
    out = []
    first = (s.get("caption") or "").splitlines()[0] if s.get("caption") else ""
    if len(first) > FIRST_LINE:
        out.append(f"the first line is {len(first)} characters: only about {FIRST_LINE} show before \"more\"")
    if len(s.get("hashtags") or []) > MAX_TAGS:
        out.append(f"Instagram allows {MAX_TAGS} hashtags")
    if not s.get("keywords"):
        out.append("no search keywords")
    return out


def write(plan_path: Path, tone: str | None = None, extra: str | None = None) -> dict:
    plan_path = Path(plan_path)
    plan = read_json(plan_path)
    if not plan:
        raise ReelError(f"could not read {plan_path}")
    s = generate(plan, tone, extra)
    s["checks"] = checks(s)
    base = plan_path.with_name(plan_path.name[:-len(".plan.json")])
    Path(f"{base}.caption.txt").write_text(post_text(s))
    write_json(Path(f"{base}.social.json"), s)
    return {"plan": str(plan_path), "caption_file": f"{base}.caption.txt", **s}
