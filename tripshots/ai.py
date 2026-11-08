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


LOGIN_HELP = ("Claude Code isn't logged in for TripShots. In a terminal run `claude auth login` (or `claude`, then "
              "/login), then check with `tripshots doctor`. If it says you're logged in but TripShots still can't use "
              "it, run `claude setup-token` and put the token in ~/.tripshots/.env as CLAUDE_CODE_OAUTH_TOKEN=... "
              "Or pick another AI with -b (minimax, api) or -b none")
_AUTH_WORDS = ("not logged in", "please run /login", "invalid api key", "oauth token has expired", "token expired",
               "authentication_error", "authentication failed", "credit balance is too low", "401")


class AIAuthError(ReelError):
    """The AI backend can't be used at all (not logged in, bad key, no credit): stop asking it."""


class ClaudeCLI(Backend):
    name = "claude-cli"

    def __init__(self, model: str | None = None):
        self.model = model or os.environ.get("TRIPSHOTS_CLAUDE_MODEL") or None
        self.broken: str | None = None  # set on the first login/key error: later calls fail at once

    @staticmethod
    def login_status() -> dict | None:
        """`claude auth status` (local, no request). None when this Claude Code version can't tell."""
        try:
            p = run(["claude", "auth", "status", "--json"], timeout=30, check=False)
            d = json.loads(p.stdout)
            return d if isinstance(d, dict) and "loggedIn" in d else None
        except Exception:
            return None

    def ask(self, prompt, images=None, max_tokens=4000):
        if self.broken:
            raise AIAuthError(self.broken)
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
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            data = None
        if proc.returncode != 0 or (isinstance(data, dict) and data.get("is_error")):
            msg = str(data.get("result")) if isinstance(data, dict) and data.get("result") else \
                (proc.stderr or proc.stdout or "").strip()[-300:]
            if any(w in msg.lower() for w in _AUTH_WORDS):
                self.broken = f"{LOGIN_HELP}. (Claude Code said: {msg.strip()[:120]})"
                raise AIAuthError(self.broken)
            raise ReelError(f"claude CLI error: {msg[:300]}")
        if data is None:
            return proc.stdout
        return data.get("result", "")


class AnthropicAPI(Backend):
    """The Anthropic Messages API, or any compatible endpoint (MiniMax)."""

    def __init__(self, base_url=None, api_key=None, model=None, name: str = "api"):
        import anthropic
        self.name = name
        env_model = os.environ.get("TRIPSHOTS_MODEL") or ""
        self.model = model or (env_model if env_model and not env_model.lower().startswith("minimax") else
                               "claude-sonnet-5-5")
        kw = {}
        if base_url or os.environ.get("ANTHROPIC_BASE_URL"):
            kw["base_url"] = base_url or os.environ["ANTHROPIC_BASE_URL"]
        self.client = anthropic.Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"), **kw)
        self.broken: str | None = None

    def ask(self, prompt, images=None, max_tokens=4000):
        import anthropic
        if self.broken:
            raise AIAuthError(self.broken)
        content = []
        for p in images or []:
            content.append({"type": "image", "source": {
                "type": "base64", "media_type": "image/jpeg",
                "data": base64.b64encode(Path(p).read_bytes()).decode()}})
        content.append({"type": "text", "text": prompt})
        try:
            msg = self.client.messages.create(model=self.model, max_tokens=max_tokens,
                                              messages=[{"role": "user", "content": content}])
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as e:
            self.broken = f"{self.name}: the key was refused ({str(e)[:120]})"
            raise AIAuthError(self.broken)
        except anthropic.APIStatusError as e:
            if any(w in str(e).lower() for w in _AUTH_WORDS):
                self.broken = f"{self.name}: {str(e)[:160]}"
                raise AIAuthError(self.broken)
            raise
        return "".join(getattr(b, "text", "") for b in msg.content)


class Chain(Backend):
    """Automatic mode: the first AI that works, moving on to the next when one refuses (not logged in, bad key,
    no credit). Verdicts are stored under the name of the AI that actually gave them."""

    def __init__(self, backends: list[Backend]):
        self.backends = backends
        self.i = 0

    @property
    def name(self) -> str:
        return self.backends[self.i].name

    def ask(self, prompt, images=None, max_tokens=4000):
        while True:
            b = self.backends[self.i]
            try:
                return b.ask(prompt, images, max_tokens)
            except AIAuthError as e:
                if self.i + 1 >= len(self.backends):
                    raise
                self.i += 1
                log(f"{b.name} can't be used ({str(e)[:100]}); switching to {self.backends[self.i].name}")


def _minimax() -> AnthropicAPI:
    key = os.environ.get("MINIMAX_API_KEY")
    if not key:
        raise ReelError("MINIMAX_API_KEY is not set")
    model = os.environ.get("TRIPSHOTS_MINIMAX_MODEL") or (
        os.environ.get("TRIPSHOTS_MODEL") if (os.environ.get("TRIPSHOTS_MODEL") or "").lower().startswith("minimax")
        else None) or "MiniMax-M3"
    return AnthropicAPI(base_url=os.environ.get("MINIMAX_BASE_URL", "https://api.minimax.io/anthropic"),
                        api_key=key, model=model, name="minimax")


def _claude_ready() -> bool:
    st = ClaudeCLI.login_status()
    return st is None or bool(st.get("loggedIn")) or bool(os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"))


def get_backend(name: str | None = None) -> Backend | None:
    """The AI to use. auto: Claude Code (your subscription) if it's installed and logged in, then MiniMax, then the
    Anthropic API, each only if set up; if one stops working mid-run (logged out, key refused), the next takes over."""
    name = (name or os.environ.get("TRIPSHOTS_BACKEND") or "auto").lower()
    if name == "none":
        return None
    if name == "minimax":
        return _minimax()
    if name == "claude-cli":
        if not which("claude"):
            raise ReelError("`claude` CLI not found. Install Claude Code and run `claude` once to log in.")
        if not _claude_ready():
            raise AIAuthError(LOGIN_HELP)
        return ClaudeCLI()
    if name == "api":
        return AnthropicAPI()
    if name != "auto":
        raise ReelError(f"unknown backend '{name}' (use auto, claude-cli, api, minimax or none)")
    chain: list[Backend] = []
    skipped = None
    if which("claude"):
        if _claude_ready():
            chain.append(ClaudeCLI())
        else:
            skipped = "Claude Code is installed but not logged in (`claude auth login`)"
    if os.environ.get("MINIMAX_API_KEY"):
        chain.append(_minimax())
    if os.environ.get("ANTHROPIC_API_KEY"):
        chain.append(AnthropicAPI())
    if not chain:
        if skipped:
            raise AIAuthError(LOGIN_HELP)
        log("no AI backend found (claude CLI / API key); using heuristics only")
        return None
    if skipped:
        log(f"{skipped}; using {chain[0].name}")
    return chain[0] if len(chain) == 1 else Chain(chain)


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
            except AIAuthError:
                raise  # no point retrying, or sending the other sheets
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


HOOK_TYPES = ("curiosity", "pov", "number", "bold", "feeling", "tease")
_CLICHES = ("wanderlust", "vibes", "adventure awaits", "paradise", "breathtaking", "take me back", "living my best")


def clean_line(t: str) -> str:
    """On-screen text without emoji or symbols the fonts can't draw (they'd show as empty boxes)."""
    import unicodedata
    keep = []
    for ch in str(t):
        cat = unicodedata.category(ch)
        if cat[0] in "LNPZ" or ch in "&°%$€£+#@'’·":
            keep.append(ch)
    return " ".join("".join(keep).split()).strip()


def _hook_rules(h: str, fmt: str) -> float:
    """A cheap second opinion on a hook line (0..10): short, concrete, opens a question, no clichés."""
    w = h.split()
    v = 6.0
    v += 1.0 if 2 <= len(w) <= 7 else -2.5
    low = h.lower()
    v -= 2.0 * sum(c in low for c in _CLICHES)
    v += 0.8 if any(ch.isdigit() for ch in h) else 0.0
    v += 0.8 if low.startswith("pov") and fmt in ("pov", "montage") else 0.0
    v += 0.6 if "?" in h or any(x in low for x in ("wait", "nobody", "didn't", "never", "why", "how", "this is")) else 0
    return max(0.0, min(10.0, v))


def write_story_copy(backend: Backend, plan: dict, shots_by_id: dict, style: dict, fmt: str = "montage",
                     places: list[str] | None = None, words: dict | None = None, extra: dict | None = None) -> dict:
    """The reel's words for its format: three hook candidates scored on a rubric (the best is used), the closing
    line, a caption that asks one question and names the places, and a few hashtags."""
    segs = plan["segments"]
    tags, notes = [], []
    for s in segs:
        a = shots_by_id.get(s["shot_id"], {}).get("ai", {})
        tags += a.get("tags", [])[:5]
        if a.get("note"):
            notes.append(f"{s.get('role', '')}: {a['note']}")
    places = [p for p in dict.fromkeys(places or []) if p]
    av = style.get("_avoid_hooks") or []
    extra = extra or {}
    fmt_rule = {
        "montage": 'a curiosity gap or a feeling, specific to these places (e.g. "I almost skipped this stop")',
        "pov": 'starts with "POV:" and names a specific feeling (e.g. "POV: the road finally opens up")',
        "list": f'promises a numbered list of these {extra.get("n_places") or len(places)} places '
                f'(e.g. "{extra.get("n_places") or 3} stops in Utah you can\'t skip")',
        "series": f'uses the stem "Day {extra.get("day") or "N"} of" + the trip (e.g. "Day {extra.get("day") or 4} of our '
                  'West Coast road trip")',
        "reveal": 'teases a payoff at the end without saying what it is (e.g. "Wait for the last one")',
    }[fmt if fmt in ("montage", "pov", "list", "series", "reveal") else "montage"]
    sound = ""
    if words and words.get("lines"):
        lines = "; ".join(ln.get("english") or ln["text"] for ln in words["lines"][:8])
        sound = (f"\nThe sound is {words.get('kind')} ({words.get('language') or '?'}), in English: \"{lines[:400]}\". "
                 "Make the hook set up these words (the picture answers them), without repeating them.")
    prompt = f"""You write the words for a short travel Reel made from the creator's own footage.
Format: {fmt}. Places: {', '.join(places) or 'unknown'}.
What the shots show, in story order: {'; '.join(notes[:10]) or ', '.join(dict.fromkeys(tags))}.{sound}
Tone: {style.get('caption', {}).get('tone')}.
Return ONLY JSON: {{"hooks": [{{"text": "...", "type": "curiosity|pov|number|bold|feeling|tease",
"clarity": 0-10, "curiosity": 0-10, "emotion": 0-10}}], "cta": "...", "caption": "...", "hashtags": ["..."]}}
- hooks: 3 different on-screen opening lines, max 7 words each, readable in one second, never invented facts.
  This format's hook {fmt_rule}. Score each honestly: clarity (reads at a glance), curiosity (makes you stay to
  see), emotion (makes you feel something). No clichés (wanderlust, vibes, paradise, breathtaking).
  {('Use a clearly different angle from: ' + '; '.join(chr(34) + h + chr(34) for h in av) + '.') if av else ''}
- cta: closing line, max 6 words, worth sending to a friend (e.g. "Send this to your road trip person").
- caption: 1-3 short natural lines that name the places in plain words (people search them) and end with ONE
  question the viewer can answer in a comment.
- hashtags: {min(6, int(style.get('caption', {}).get('hashtags', 6) or 6))} specific ones (places first), without #."""
    try:
        data = extract_json(backend.ask(prompt, None, max_tokens=900))
    except Exception as e:
        debug(f"story copy failed: {e}")
        return {}
    hooks = []
    for h in data.get("hooks") or []:
        if not isinstance(h, dict) or not str(h.get("text", "")).strip():
            continue
        t = clean_line(str(h["text"]).strip().strip('"'))
        ai_score = sum(float(h.get(k, 5) or 5) for k in ("clarity", "curiosity", "emotion")) / 3
        hooks.append({"text": t, "type": str(h.get("type") or "curiosity"),
                      "score": round(0.65 * ai_score + 0.35 * _hook_rules(t, fmt), 2)})
    hooks = [h for h in hooks if h["text"] not in av] or hooks
    hooks.sort(key=lambda h: -h["score"])
    return {"hooks": hooks, "hook": hooks[0]["text"] if hooks else None,
            "hook_type": hooks[0]["type"] if hooks else None,
            "cta": clean_line(str(data.get("cta", ""))), "caption": str(data.get("caption", "")).strip(),
            "hashtags": [str(h).lstrip("#").replace(" ", "") for h in data.get("hashtags", [])]}


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
