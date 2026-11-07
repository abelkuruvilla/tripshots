"""Vision/LLM backends and the prompts that use them.

Backends
  claude-cli : runs the `claude` CLI headless (uses your Claude Pro/Max subscription login)
  api        : any Anthropic-compatible Messages API (Claude API key, or MiniMax)
  minimax    : shorthand for api at https://api.minimax.io/anthropic with MiniMax-M3
  none       : no AI; technical heuristics only
"""
from __future__ import annotations

import base64
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .util import ReelError, debug, log, run, which


class Backend:
    name = "none"

    def ask(self, prompt: str, images: list[Path] | None = None, max_tokens: int = 4000) -> str:
        raise NotImplementedError


class ClaudeCLI(Backend):
    name = "claude-cli"

    def __init__(self, model: str | None = None):
        self.model = model or os.environ.get("TRIPSHOTS_CLAUDE_MODEL") or None

    def ask(self, prompt, images=None, max_tokens=4000):
        images = images or []
        if images:
            listing = "\n".join(f"- {p.resolve()}" for p in images)
            prompt = (f"First use the Read tool to view each of these image files:\n{listing}\n\n"
                      f"Then complete the task below. Do not modify any files.\n\n{prompt}")
        cmd = ["claude", "-p", prompt, "--output-format", "json", "--allowedTools", "Read"]
        dirs = sorted({str(p.resolve().parent) for p in images})
        for d in dirs:
            cmd += ["--add-dir", d]
        if self.model:
            cmd += ["--model", self.model]
        proc = run(cmd, cwd=dirs[0] if dirs else None, timeout=600, check=False)
        if proc.returncode != 0:
            raise ReelError(f"claude CLI failed: {(proc.stderr or proc.stdout)[-400:]}")
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return proc.stdout
        if data.get("is_error"):
            raise ReelError(f"claude CLI error: {str(data.get('result'))[:300]}")
        return data.get("result", "")


class AnthropicAPI(Backend):
    name = "api"

    def __init__(self, base_url=None, api_key=None, model=None):
        import anthropic
        self.model = model or os.environ.get("TRIPSHOTS_MODEL") or "claude-sonnet-5-5"
        kw = {}
        if base_url or os.environ.get("ANTHROPIC_BASE_URL"):
            kw["base_url"] = base_url or os.environ["ANTHROPIC_BASE_URL"]
        self.client = anthropic.Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"), **kw)

    def ask(self, prompt, images=None, max_tokens=4000):
        content = []
        for p in images or []:
            content.append({"type": "image", "source": {
                "type": "base64", "media_type": "image/jpeg",
                "data": base64.b64encode(Path(p).read_bytes()).decode()}})
        content.append({"type": "text", "text": prompt})
        msg = self.client.messages.create(model=self.model, max_tokens=max_tokens,
                                          messages=[{"role": "user", "content": content}])
        return "".join(getattr(b, "text", "") for b in msg.content)


def get_backend(name: str | None = None) -> Backend | None:
    name = (name or os.environ.get("TRIPSHOTS_BACKEND") or "auto").lower()
    if name == "none":
        return None
    if name == "minimax" or (name == "auto" and os.environ.get("MINIMAX_API_KEY")
                             and not which("claude") and not os.environ.get("ANTHROPIC_API_KEY")):
        key = os.environ.get("MINIMAX_API_KEY")
        if not key:
            raise ReelError("MINIMAX_API_KEY is not set")
        return AnthropicAPI(base_url=os.environ.get("MINIMAX_BASE_URL", "https://api.minimax.io/anthropic"),
                            api_key=key, model=os.environ.get("TRIPSHOTS_MODEL", "MiniMax-M3"))
    if name == "claude-cli" or (name == "auto" and which("claude")):
        if not which("claude"):
            raise ReelError("`claude` CLI not found. Install Claude Code and run `claude` once to log in.")
        return ClaudeCLI()
    if name == "api" or (name == "auto" and os.environ.get("ANTHROPIC_API_KEY")):
        return AnthropicAPI()
    if name == "auto":
        log("no AI backend found (claude CLI / API key); using heuristics only")
        return None
    raise ReelError(f"unknown backend '{name}' (use claude-cli, api, minimax or none)")


def extract_json(text: str):
    """Pull the first JSON object/array out of a model reply."""
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    starts = [i for i in (text.find("["), text.find("{")) if i >= 0]
    for start in sorted(starts):
        opener = text[start]
        closer = "]" if opener == "[" else "}"
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            c = text[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            elif c == '"':
                in_str = True
            elif c == opener:
                depth += 1
            elif c == closer:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break
    raise ReelError(f"model reply had no valid JSON: {text[:200]!r}")


# --------------------------------------------------------------------- scoring
AI_VERSION = 2  # bump when the prompt or the fields change: stored verdicts of older versions get re-asked by `analyze`

SCENES = ["landscape", "mountains", "water", "beach", "forest", "desert", "snow", "sky", "cityscape", "street",
          "architecture", "interior", "food", "people", "portrait", "group", "wildlife", "plants", "transport",
          "activity", "event", "night", "aerial", "detail", "document", "screenshot", "other"]
TIMES = ["sunrise", "morning", "midday", "afternoon", "golden-hour", "sunset", "blue-hour", "night", "indoor", "unknown"]
WEATHER = ["clear", "partly-cloudy", "overcast", "fog", "rain", "snow", "storm", "unknown"]
ISSUES = ["blurry", "motion-blur", "shaky", "out-of-focus", "dark", "overexposed", "low-contrast", "noisy",
          "tilted", "cluttered", "obstructed", "finger", "lens-flare", "low-res", "accidental"]
MOTIONS = ["static", "pan", "tilt", "push", "drone", "walk", "timelapse", "handheld"]

SCORE_PROMPT = """You are cataloguing someone's personal travel photos and video clips. Your descriptions are reused for
many things: searching the library, picking photos for collages and albums, and editing Instagram Reels.

The contact sheet image(s) show the files. Every tile is ONE photo or ONE video shot, labelled with its ID in a yellow
box (the bottom label says photo or video length). Technical measurements:
{table}

For EVERY ID, describe what is actually visible. Be factual and specific; never guess facts the picture doesn't show.
- caption: one plain sentence, max 15 words ("Turquoise lake below snowy peaks at sunrise").
- description: 1-3 sentences: subject, setting, light, notable details. Useful for search and for other AIs.
- tags: 3-12 lowercase search words: subjects, setting, activity, colours that matter ("lake","mountain","reflection").
- subjects: up to 4 main things, most important first: [{{"label": "...", "box": [x0,y0,x1,y1]}}], boxes as
  fractions 0..1 of THAT PHOTO (ignore the grey tile border). For a wide vista, box its most interesting part.
- scene: one of {scenes}.
- setting: "outdoor", "indoor" or "unknown".  time_of_day: one of {times}.  weather: one of {weather}.
- people: {{"count": number of clearly visible people (0 if none), "activity": what they do, or ""}}.
- text: visible text worth reading (signs, menus), max 60 characters, else "".
- landmark: the name of a famous, clearly recognisable place or landmark, else null. Never guess.
- aesthetic: 1-10 as a photograph anyone would want to keep: 9-10 striking light, composition and moment; 7-8 strong;
  5-6 ordinary snapshot; 1-4 weak.
- issues: problems you can see, from {issues}; [] if none.
- usable: false for accidental, pocket, blurry or screenshot-like shots nobody would share.
- duplicate_of: the ID of an earlier, better-or-equal tile in this sheet showing nearly the same view, else null.
For Instagram Reels specifically:
- score 1-10 as a reel shot (scroll-stopping scale, light, movement; static clutter scores low).
- role: "hook" (grabs attention in the first second), "closer" (calm, wide, satisfying ending) or "any".
- mood: "calm" or "dynamic".  motion: one of {motions} (camera movement, best guess).
- subject_x: horizontal centre of the first subject, 0.0 (left) .. 1.0 (right).
- note: max 10 words on why it is good or weak.

Reply with ONLY a JSON array, one object per ID, for example:
[{{"id":"S001","caption":"Mirror-still lake below snowy peaks at sunrise","description":"A glassy alpine lake reflects
snow-capped mountains under pink sunrise light; pines frame the left shore.","tags":["lake","mountains","reflection",
"sunrise","pine trees"],"subjects":[{{"label":"mountain reflection","box":[0.18,0.2,0.82,0.7]}}],"scene":"mountains",
"setting":"outdoor","time_of_day":"sunrise","weather":"clear","people":{{"count":0,"activity":""}},"text":"",
"landmark":null,"aesthetic":9,"issues":[],"usable":true,"duplicate_of":null,"score":9,"role":"hook","mood":"calm",
"motion":"static","subject_x":0.5,"note":"mirror lake at first light"}}]"""


def _table(shots: list[dict]) -> str:
    rows = []
    for s in shots:
        m = s["metrics"]
        if s["kind"] == "photo":
            rows.append(f"{s['id']}: photo {s['w']}x{s['h']}, brightness {m['bright']:.2f}")
        else:
            rows.append(f"{s['id']}: video {s['dur']:.1f}s @{s['fps']:.0f}fps {s['w']}x{s['h']}, "
                        f"camera-move {m['pan'] * 100:.1f}%/sample, shake {m['shake'] * 1000:.1f}, "
                        f"brightness {m['bright']:.2f}")
    return "\n".join(rows)


def _norm_box(b):
    try:
        if isinstance(b, (list, tuple)) and len(b) == 4:
            v = [max(0.0, min(1.0, float(x))) for x in b]
            if v[2] > v[0] and v[3] > v[1]:
                return [round(x, 3) for x in v]
    except (TypeError, ValueError):
        pass
    return None


def _one(v, allowed, default):
    v = str(v or "").strip().lower()
    return v if v in allowed else default


def _num(v, lo, hi, default):
    try:
        return float(max(lo, min(hi, float(v))))
    except (TypeError, ValueError):
        return default


def _norm_score(d: dict) -> dict:
    subjects = []
    for sj in (d.get("subjects") or [])[:4]:
        if isinstance(sj, dict) and sj.get("label"):
            subjects.append({"label": str(sj["label"])[:40].lower(), "box": _norm_box(sj.get("box"))})
    box = _norm_box(d.get("subject_box")) or (subjects[0]["box"] if subjects else None)
    sx = d.get("subject_x")
    if sx is None and box:
        sx = (box[0] + box[2]) / 2
    ppl = d.get("people") if isinstance(d.get("people"), dict) else {}
    out = {
        "v": AI_VERSION,
        # app-neutral description (catalogue, search, collages, other AI tasks)
        "caption": str(d.get("caption") or "")[:120],
        "description": str(d.get("description") or "")[:500],
        "tags": list(dict.fromkeys(str(t).lower().strip() for t in (d.get("tags") or []) if str(t).strip()))[:12],
        "subjects": subjects,
        "scene": _one(d.get("scene"), SCENES, "other"),
        "setting": _one(d.get("setting"), ("outdoor", "indoor", "unknown"), "unknown"),
        "time_of_day": _one(d.get("time_of_day"), TIMES, "unknown"),
        "weather": _one(d.get("weather"), WEATHER, "unknown"),
        "people": {"count": int(_num(ppl.get("count"), 0, 999, 0)), "activity": str(ppl.get("activity") or "")[:60]},
        "text": str(d.get("text") or "")[:80],
        "landmark": (str(d["landmark"])[:60] if d.get("landmark") not in (None, "", "null", "none") else None),
        "aesthetic": _num(d.get("aesthetic"), 1, 10, _num(d.get("score"), 1, 10, 5.0)),
        "issues": [i for i in (str(x).lower() for x in (d.get("issues") or [])) if i in ISSUES][:6],
        "usable": bool(d.get("usable", True)),
        # reel editing (planner.py reads these)
        "score": _num(d.get("score"), 1, 10, 5.0),
        "motion": _one(d.get("motion"), MOTIONS, "static"),
        "subject_x": _num(sx, 0, 1, 0.5),
        "subject_box": box,
        "role": d.get("role") if d.get("role") in ("hook", "closer", "any") else "any",
        "mood": d.get("mood") if d.get("mood") in ("calm", "dynamic") else "calm",
        "note": str(d.get("note", ""))[:80],
        "duplicate_of": str(d["duplicate_of"]).upper() if d.get("duplicate_of") else None,
    }
    return out


def score_shots(shots: list[dict], backend: Backend, work: Path, rescore: bool = False,
                workers: int = 3, min_version: int = 0) -> dict[str, dict]:
    """AI verdict per shot. Verdicts are stored permanently in the library, keyed by file
    content + position in the clip, so a shot is only ever sent to the AI once (whatever
    folder, filter or run it shows up in). Only never-seen shots are put on contact sheets."""
    from . import library as lib
    from .text import contact_sheets

    by_id = {s["id"]: s for s in shots}
    key_of = {s["id"]: lib.shot_key(s) for s in shots}
    id_of = {k: i for i, k in key_of.items()}

    def to_run_ids(v: dict) -> dict:
        v = dict(v)
        dup = v.get("duplicate_of")
        v["duplicate_of"] = id_of.get(dup) if dup else None  # stored as shot key
        return v

    if rescore:
        n = lib.forget_scores(list(key_of.values()))
        if n:
            log(f"forgot {n} stored AI verdicts for these shots")
    stored = lib.get_scores(list(key_of.values()))
    # make accepts any stored verdict; analyze (min_version=AI_VERSION) re-asks for older, thinner ones
    stored = {k: v for k, v in stored.items() if int(v.get("v", 1)) >= min_version}
    results = {i: to_run_ids(stored[k]) for i, k in key_of.items() if k in stored}
    todo_shots = [s for s in shots if s["id"] not in results]
    if not todo_shots:
        log(f"all {len(shots)} shots already judged by AI (stored in the library); nothing sent")
        return results
    log(f"AI: {len(results)} shots already judged, {len(todo_shots)} new -> sending to {backend.name}")
    sheets = contact_sheets(todo_shots, work / "sheets", per_sheet=8, cols=4, tile=(440, 440))

    def job(item):
        sheet, ids = item
        prompt = SCORE_PROMPT.format(table=_table([by_id[i] for i in ids]), scenes=", ".join(SCENES),
                                     times=", ".join(TIMES), weather=", ".join(WEATHER), issues=", ".join(ISSUES),
                                     motions=", ".join(MOTIONS))
        for attempt in range(2):
            try:
                data = extract_json(backend.ask(prompt, [sheet], max_tokens=8000))
                if isinstance(data, dict):
                    data = data.get("shots") or list(data.values())
                got = {str(d.get("id")).upper(): _norm_score(d) for d in data if isinstance(d, dict) and d.get("id")}
                return {i: got[i] for i in ids if i in got}
            except Exception as e:
                log(f"  scoring {sheet.name} failed (attempt {attempt + 1}): {e}")
        return {}

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for n, got in enumerate(ex.map(job, sheets), 1):
            if got:
                # store with shot keys (run ids like S014 change between runs)
                lib.put_scores({key_of[i]: {**v, "duplicate_of": key_of.get(v.get("duplicate_of") or "")}
                                for i, v in got.items()}, backend.name)
                results.update({i: {**v, "source": backend.name} for i, v in got.items()})
            log(f"  batch {n}/{len(sheets)} done ({len(got)} judged, saved)")
    return results


# --------------------------------------------------------------- captions/hook
def write_hook_and_caption(backend: Backend, plan: dict, shots_by_id: dict, style: dict,
                           want_hook: bool, want_cta: bool = False) -> dict:
    locs = [o["text"] for o in plan.get("overlays", []) if o["type"] == "location"]
    tags = []
    for s in plan["segments"]:
        tags += shots_by_id.get(s["shot_id"], {}).get("ai", {}).get("tags", [])
    notes = [shots_by_id.get(s["shot_id"], {}).get("ai", {}).get("note", "") for s in plan["segments"][:6]]
    av = style.get("_avoid_hooks") or []
    avoid = (" This is an alternative version: use a clearly different angle from these hooks: "
             + "; ".join(f'"{h}"' for h in av) + ".") if av else ""
    prompt = f"""You write Instagram copy for a scenic travel Reel (no people talking, music only).
Places shown: {', '.join(dict.fromkeys(locs)) or 'unknown'}
Visual subjects: {', '.join(dict.fromkeys(tags)) or 'landscapes'}
Shot notes: {'; '.join(n for n in notes if n)}
Tone: {style.get('caption', {}).get('tone')}
Return ONLY JSON: {{"hook": "...", "cta": "...", "caption": "...", "hashtags": ["..."]}}
- hook: on-screen text for the first 2 seconds, max 7 words, curiosity or POV style (e.g. "POV: you finally made it here"). Never invent facts.{avoid}
- cta: closing on-screen line, max 6 words, invites saving/sharing without being salesy (e.g. "Save this for your next road trip").
- caption: 1-3 short lines, natural, no clichés like "wanderlust vibes", may end with a soft question.
- hashtags: {style.get('caption', {}).get('hashtags', 12)} relevant tags mixing broad and niche (location-specific when known), without the # sign."""
    try:
        data = extract_json(backend.ask(prompt, None, max_tokens=800))
        out = {"caption": str(data.get("caption", "")).strip(),
               "hashtags": [str(h).lstrip("#").replace(" ", "") for h in data.get("hashtags", [])]}
        if want_hook:
            out["hook"] = str(data.get("hook", "")).strip()
        if want_cta:
            out["cta"] = str(data.get("cta", "")).strip()
        return out
    except Exception as e:
        debug(f"caption failed: {e}")
        return {}


def write_labels(backend: Backend, items: list[dict], places: list[str], tone: str) -> list[str]:
    """Short on-screen labels, one per shot, for the 'labelled montage' format."""
    lines = "\n".join(f"{i + 1}. {it.get('note') or ''} [{', '.join(it.get('tags') or [])}]" for i, it in enumerate(items))
    prompt = f"""You label the shots of a scenic travel Reel. Each shot gets a short on-screen label (1-3 words),
like a mini story beat: a place, a moment or a feeling ("Golden hour", "Highway 1", "Mile 42", "No signal", "Worth it").
Places on this trip: {', '.join(places) or 'unknown'}. Tone: {tone}.
Shots in order:
{lines}
Rules: never invent specific facts you can't see; no emojis; no hashtags; vary them; the last one can be a payoff.
Return ONLY a JSON array of {len(items)} strings."""
    try:
        data = extract_json(backend.ask(prompt, None, max_tokens=600))
        if isinstance(data, list):
            return [str(x).strip()[:28] for x in data][:len(items)]
    except Exception as e:
        debug(f"labels failed: {e}")
    return []
