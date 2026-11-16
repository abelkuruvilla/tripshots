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


_LIMIT_WORDS = ("hit your session limit", "hit your usage limit", "hit your limit", "usage limit reached",
                "session limit reached", "weekly limit", "limit will reset", "out of extra usage")


class AIAuthError(ReelError):
    """The AI backend can't be used at all (not logged in, bad key, no credit): stop asking it."""


class AILimitError(AIAuthError):
    """The AI's usage limit is spent for now: stop asking it; the work can be finished after it resets."""


class ClaudeCLI(Backend):
    name = "claude-cli"

    def __init__(self, model: str | None = None):
        self.model = model or os.environ.get("TRIPSHOTS_CLAUDE_MODEL") or None
        self.broken: str | None = None  # set on the first login/key error: later calls fail at once
        self.limited = False            # ... or when the usage limit is spent

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
            raise (AILimitError if self.limited else AIAuthError)(self.broken)
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
            if any(w in msg.lower() for w in _LIMIT_WORDS):
                self.broken, self.limited = f"the AI's usage limit is reached (Claude Code said: {msg.strip()[:120]})", True
                raise AILimitError(self.broken)
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
          "tilted", "cluttered", "obstructed", "finger", "lens-flare", "low-res", "accidental", "burned-in-text"]
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
- issues: problems you can see, from {issues}; [] if none. "burned-in-text" = titles, captions, a watermark or
  app buttons drawn ON the picture (an edited export, a saved reel, a screenshot); signs in the scene don't count.
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


# --------------------------------------------------------------- more about each shot (asked once, separately)
# Fields added after a library was described: asked on their own, for shots that already have a verdict, so a new
# field never means describing every shot again. A video tile is a strip of its start, middle and end.
ENRICH_VERSION = 1
VIBES = ["serene", "epic", "playful", "nostalgic", "romantic", "energetic", "moody", "adventurous", "cosy",
         "mysterious"]
SIZES = ["wide", "medium", "close", "detail"]
ANGLES = ["aerial", "high", "eye", "low"]
ENRICH_PROMPT = """These are travel photos and video clips already catalogued; I need a few more details about each.
Each tile is labelled with its ID. A VIDEO tile shows three moments of the clip: its start, middle and end (left to
right, or top to bottom). The tiles:
{table}

For EVERY ID give:
- vibes: the feelings it gives, up to 3, each with how strongly (0.1-1.0), from: {vibes}
- shot_size: how big the main subject is: "wide" (a whole place), "medium" (a person head to toe, a building),
  "close" (a face, an object filling the frame) or "detail" (a texture, a hand, a flower)
- angle: "aerial" (drone or plane), "high" (looking down), "eye" (eye level) or "low" (looking up)
- face: when a person's face can be seen: {{"looking": does the main person look at the camera, "eyes_open": true or
  false, "smiling": true or false}}; null when no face is visible
- videos only: action_peak: where the most happens or the best moment is: "start", "middle", "end" or "none" (nothing
  changes); first_frame: 1-10 how strong the START alone is as the opening frame of a reel (sharp, striking, already
  moving or full of promise); photos: null for both

Reply with ONLY a JSON array, one object per ID:
[{{"id":"S001","vibes":{{"serene":0.9,"romantic":0.4}},"shot_size":"wide","angle":"eye","face":null,
"action_peak":"middle","first_frame":7}}]"""


def _norm_enrich(d: dict, video: bool) -> dict:
    vib = d.get("vibes") if isinstance(d.get("vibes"), dict) else {}
    vibes = {k: round(_num(v, 0, 1, 0), 2) for k, v in vib.items() if k in VIBES}
    vibes = dict(sorted(vibes.items(), key=lambda kv: -kv[1])[:3])
    face = d.get("face") if isinstance(d.get("face"), dict) else None
    out = {"x": ENRICH_VERSION, "vibes": vibes, "shot_size": _one(d.get("shot_size"), SIZES, None),
           "angle": _one(d.get("angle"), ANGLES, None),
           "face": {k: bool(face.get(k)) for k in ("looking", "eyes_open", "smiling")} if face else None}
    if video:
        out["action_peak"] = _one(d.get("action_peak"), ("start", "middle", "end", "none"), None)
        out["first_frame"] = _num(d.get("first_frame"), 1, 10, None) if d.get("first_frame") is not None else None
    return out


DETAIL_KEYS = ("x", "vibes", "shot_size", "angle", "face", "action_peak", "first_frame")


def apply_enriched(shots: list[dict]) -> dict:
    """Put the stored extra details (ENRICH_PROMPT) on the shots that have them; returns the stored verdicts."""
    from . import library as lib
    keys = {s["id"]: lib.shot_key(s) for s in shots}
    stored = lib.get_scores(list(keys.values()))
    for s in shots:
        v = stored.get(keys[s["id"]])
        if v and int(v.get("x") or 0) >= ENRICH_VERSION and isinstance(s.get("ai"), dict):
            s["ai"].update({k: v[k] for k in DETAIL_KEYS if k in v})
    return stored


def enrich_shots(shots: list[dict], backend: Backend, work: Path, limit: int | None = None,
                 workers: int = 3) -> int:
    """Ask for ENRICH_PROMPT's fields about shots that have a stored verdict without them; merged into the stored
    verdict (library) and into s["ai"]. `limit`: at most this many, the best first. Returns how many were done."""
    from . import library as lib
    from .insight import strip
    from .text import contact_sheets
    keys = {s["id"]: lib.shot_key(s) for s in shots}
    stored = apply_enriched(shots)
    todo = [s for s in shots if keys[s["id"]] in stored and int(stored[keys[s["id"]]].get("x") or 0) < ENRICH_VERSION]
    if not todo:
        return 0
    todo.sort(key=lambda s: -float((s.get("ai") or {}).get("score") or 0))
    if limit is not None:
        todo = todo[:limit]
    log(f"AI: a few more details about {len(todo)} shot(s) (vibe, shot size, angle, faces, best moment)")
    tiles = []
    for s in todo:
        st = strip(s) if s.get("kind") == "video" else None
        tiles.append({**s, "thumb": str(st or s.get("thumb"))})
    sheets = contact_sheets(tiles, work / "sheets_more", per_sheet=8, cols=4, tile=(440, 440))
    by_id = {s["id"]: s for s in todo}

    def job(item):
        sheet, ids = item
        for attempt in range(2):
            try:
                table = "\n".join(f"{i}: " + ("video, three moments" if by_id[i].get("kind") == "video" else "photo")
                                  for i in ids)
                data = extract_json(backend.ask(ENRICH_PROMPT.format(vibes=", ".join(VIBES), table=table), [sheet],
                                                max_tokens=4000))
                if isinstance(data, dict):
                    data = data.get("shots") or list(data.values())
                got = {str(d.get("id")).upper(): d for d in data if isinstance(d, dict) and d.get("id")}
                return {i: _norm_enrich(got[i], by_id[i].get("kind") == "video") for i in ids if i in got}
            except AIAuthError:
                raise
            except Exception as e:
                log(f"  details for {sheet.name} failed (attempt {attempt + 1}): {e}")
        return {}
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for n, got in enumerate(ex.map(job, sheets), 1):
            if got:
                merged = {}
                for i, v in got.items():
                    old = {k: x for k, x in stored[keys[i]].items() if k != "source"}
                    merged[keys[i]] = {**old, **v}
                    if isinstance(by_id[i].get("ai"), dict):
                        by_id[i]["ai"].update(v)
                lib.put_scores(merged, backend.name)
                done += len(got)
            if n % 10 == 0 or n == len(sheets):
                log(f"  details {n}/{len(sheets)} sheets")
    return done


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
    out = " ".join("".join(keep).split()).strip()
    return re.sub(r"\.{4,}|…\.+|\.+…", "...", out)  # "dream about...." trails off with three dots, like any line


_SPOKEN_NUMBERS = {"two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "twelve", "twenty",
                   "thirty", "fifty", "hundred", "thousand", "million", "dozen", "half", "zero", "km", "miles", "hours",
                   "days", "nights", "feet", "meters", "°"}
# openings that spend the first second saying nothing (greetings, video preambles, asking for attention)
_DEAD_OPENERS = re.compile(r"(?i)^\s*(?:hey|hi|hello|welcome|so|ok(?:ay)?|today|guys)\b|^\s*(?:stop scrolling|don'?t "
                           r"scroll)|\bin (?:this|today'?s) (?:video|reel)\b|\bi'?m going to show you\b")


def _concrete(words: list[str]) -> list[int]:
    """Positions of the checkable words in a hook: a figure, a spoken number or unit, a name (a capital that isn't
    the first word, when the line isn't all in capitals or title case)."""
    caps = [x for x in words if x[:1].isupper()]
    named = len(caps) < max(2, 0.7 * len(words))
    out = []
    for i, x in enumerate(words):
        bare = x.strip(".,!?:;'\"").lower()
        if any(ch.isdigit() for ch in x) or bare in _SPOKEN_NUMBERS or (named and i and x[:1].isupper()):
            out.append(i)
    return out


def _hook_rules(h: str, fmt: str) -> float:
    """A cheap second opinion on a hook line (0..10): short, concrete (a number or a name, early in the line),
    opens a question, no clichés, no greeting or preamble, no emoji or hashtag. Text can't tell which of two good
    hooks will travel; this catches the weak ones."""
    w = h.split()
    v = 6.0
    v += 1.0 if 2 <= len(w) <= 7 else -2.5
    low = h.lower()
    v -= 2.0 * sum(c in low for c in _CLICHES)
    pos = _concrete(w)
    v += 0.8 if pos else 0.0
    v += 0.4 if pos and pos[0] <= 2 else 0.0                     # the interesting word comes first
    v += 0.8 if low.startswith("pov") and fmt in ("pov", "montage") else 0.0
    v += 0.6 if "?" in h or any(x in low for x in ("wait", "nobody", "didn't", "never", "why", "how", "this is")) else 0
    v -= 3.0 if _DEAD_OPENERS.search(h) else 0.0
    v -= 1.5 if re.search(r"(?<!\w)#\w", h) or re.search("[\U0001F300-\U0001FAFF☀-➿]", h) else 0.0
    return max(0.0, min(10.0, v))


def misplaced(text: str, facts: list[dict]) -> list[tuple[str, str, str]]:
    """Names a text puts in the wrong region: [(name, the region it says, the region it is in)]. `facts`: what
    is known per shot {landmark, place, region}. Only a region named in the same clause as the name counts
    ("Utah's Half Dome", "Lake McDonald in California"); "from Half Dome in California to Utah" is fine."""
    regions = {str(f["region"]) for f in facts or [] if f and f.get("region")}
    home: dict[str, set] = {}
    for f in facts or []:
        for k in ("landmark", "place"):
            name = str((f or {}).get(k) or "").split(",")[0].strip()
            if len(name) >= 4 and f.get("region") and name not in regions:
                home.setdefault(name, set()).add(str(f["region"]))
    out = []
    for clause in re.split(r"[.;:!?\n,]| then | and then | to ", str(text or "")):
        said = [r for r in regions if re.search(rf"\b{re.escape(r)}\b", clause, re.I)]
        for name, true in home.items():
            if said and not (set(said) & true) and re.search(rf"\b{re.escape(name)}\b", clause, re.I):
                out.append((name, said[0], sorted(true)[0]))
    return out


def true_caption(backend: Backend, caption: str, facts: list[dict]) -> str:
    """A caption with every place in its own region: one correction is asked for, and a sentence that still
    has a place wrong is dropped (what a caption says about a trip is read as fact)."""
    bad = misplaced(caption, facts)
    if not bad:
        return caption
    wrong = "; ".join(f"{n} is in {t}, not {s}" for n, s, t in bad)
    debug(f"caption had places wrong ({wrong}): asking again")
    try:
        again = str(backend.ask(f"This Reel caption gets places wrong: {wrong}.\n\n{caption}\n\nRewrite it with every "
                                "place in its right region, changing nothing else. Return ONLY the caption.",
                                None, max_tokens=400)).strip().strip('"')
        if again and len(again) < 3 * len(caption) + 80 and not misplaced(again, facts):
            return again
    except Exception as e:
        debug(f"caption correction failed: {e}")
    kept = [ln for ln in re.split(r"(?<=[.!?])\s+|\n+", caption) if ln.strip() and not misplaced(ln, facts)]
    regions = list(dict.fromkeys(str(f["region"]) for f in facts if f and f.get("region")))
    if regions and not any(re.search(rf"\b{re.escape(r)}\b", " ".join(kept), re.I) for r in regions):
        kept.insert(0, (", ".join(regions[:-1]) + " and " + regions[-1] if len(regions) > 1 else regions[0]) + ".")
    return "\n".join(kept)


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
    ref, model, more, rule = extra.get("reference") or {}, "", "", ""
    kind = extra.get("text_kind")
    facts = extra.get("facts") or []

    def where(f: dict) -> str:
        bits = [f"{k}: {f[k]}" for k in ("landmark", "place", "region") if f.get(k)]
        return ("; ".join(bits) + (" (position from a picture taken minutes apart)" if f.get("near") else "")) \
            if bits else "not known"
    if not places and facts:  # no location titles asked for: the copy still names where the trip went
        places = [p for p in dict.fromkeys(f.get(k) for k in ("region", "landmark") for f in facts) if p][:12]
    def light(i: int) -> str:  # the dusk belongs to the shot it was filmed in, not to the best-known name
        a = shots_by_id.get(segs[i].get("shot_id"), {}).get("ai", {}) if i < len(segs) else {}
        tod = str(a.get("time_of_day") or "").lower().replace("_", " ")
        plain = ("day", "midday", "morning", "afternoon", "indoor", "unknown", "none")
        return f" ({tod})" if tod and tod not in plain else ""
    spots = ""
    if facts and any(facts):
        spots = ("\nWhere each shot was filmed, in story order (the light is given where it isn't plain daylight; "
                 "a sunset, a night or a storm is only ever said of the place it is listed with):\n"
                 + "\n".join(f"{i + 1}. {where(f)}{light(i)}" for i, f in enumerate(facts)))
    if extra.get("when"):
        spots += f"\nFilmed: {extra['when']}."
    if kind in ("tease", "title", "labels") and ref:
        # the reel follows one reference's recipe: its words do a job (a line held over the opening, then the
        # answer when the cut changes gear; one title over everything; a name on every shot). Ours do the same
        # job for our trip.
        def quoted(v) -> str:
            return " / ".join(f'"{x}"' for x in v) if isinstance(v, list) else f'"{v}"'
        model = ("\nThe reel this one is modelled on shows these words on screen: "
                 + "; ".join(f"{k}: {quoted(v)}" for k, v in ref.items()) + ". Ours work the same way, about OUR trip.")
        if kind == "tease":
            n_pay = len(ref["payoff"]) if isinstance(ref.get("payoff"), list) else 1
            more = ', "tease": "...", "payoff": ' + ('"..."' if n_pay == 1 else f'[{n_pay} strings]')
            rule = ("- tease: the line held over the opening, built like the reference tease (same device, about as "
                    "long, max 7 words), true to these places. payoff: "
                    + ("the line that answers it when the montage starts, max 5 words" if n_pay == 1 else
                       f"{n_pay} lines shown one after another, each about as long as the reference's and never "
                       "longer (at most " + ", ".join(str(len(str(x).split())) for x in ref["payoff"])
                       + " words: each is on screen only as long as the reference's)")
                    + ". Read together, tease then payoff are ONE thought exactly the way the reference's are: when "
                    "the reference payoff finishes the tease's sentence (\"this is\" -> \"the faroe islands\"), ours "
                    "finishes it too and reads as a sentence; when it answers or turns it, ours does that. Each line "
                    "is something a person would say: a payoff that stands alone names what the shots after it are "
                    "(\"The gallery\", \"The camera roll\"), never a bare month, season or adjective (\"The October\"). "
                    "When the reference's own lines are true of any trip (they name none of its places: \"Money comes "
                    "back.\" -> \"This age never does. Go live it.\"), use them word for word: they are the reel's "
                    "voice, and a rewrite around one of our places is weaker.")
        elif kind == "title":
            more = ', "title": "..."'
            rule = ("- title: the one title of this reel, built like the reference title: the same device, the same "
                    "number of words give or take one, nothing added (a reference that is just a place and a year "
                    "gives just our place and our year; a place name gives our place name). True to the places and "
                    "dates above. It says what this reel is to someone who sees only the title: our trip, a place or "
                    "region on it, or the season of it. A reference title in another language or a word you don't "
                    "recognise is a name for ITS trip: ours names our trip in English (\"West Coast\", \"Out West\"), "
                    "never a lone verb or adjective (\"Touched\", \"Wander\").")
        elif kind == "labels" and facts:
            more = f', "labels": [{len(facts)} strings]'
            n_ref = len(ref["label"]) if isinstance(ref.get("label"), list) else 1
            regs = [f.get("region") for f in facts if f.get("region")]
            n_reg = len(set(regs))
            runs = sum(1 for k, r in enumerate(regs) if k == 0 or r != regs[k - 1])
            often = runs >= max(3, len(facts) / 3)  # the region changes at least every third shot
            rule = (f"- labels: the reference puts a name on every shot (see its label lines: the part that changes "
                    f"from one to the next is the name; it shows {'a new name on almost every shot' if n_ref > 3 else 'few names'}"
                    f"). Give that name for each of our {len(facts)} shots, in order. Our shots were filmed in "
                    f"{n_reg} region{'s' if n_reg != 1 else ''}, {runs} one after another. "
                    + ("When the reference's names are regions (states, countries), ours are too: each shot's "
                       "region, exactly as listed. " if often else
                       "Our region changes too seldom to carry a name per shot: ")
                    + "When the reference names places, or the region can't carry it, use the best-known name the "
                    "list gives for the shot (a national park, a landmark, a city), never a county or a hamlet "
                    "nobody has heard of. ONE kind of name through the whole reel: if some shots only have a region, "
                    "every shot gets its region. Only names from that shot's line, written the way people say them, "
                    "max 3 words, without the words every reference label starts with. Neighbouring shots of one "
                    "place share a name. \"\" when a shot's place is not known.")
    prompt = f"""You write the words for a short travel Reel made from the creator's own footage.
Format: {fmt}. Places: {', '.join(places) or 'unknown'}.
What the shots show, in story order: {'; '.join(notes[:10]) or ', '.join(dict.fromkeys(tags))}.{spots}{sound}{model}
Tone: {style.get('caption', {}).get('tone')}.
Return ONLY JSON: {{"hooks": [{{"text": "...", "type": "curiosity|pov|number|bold|feeling|tease",
"clarity": 0-10, "curiosity": 0-10, "emotion": 0-10}}], "cta": "...", "caption": "...", "hashtags": ["..."]{more}}}
{rule}
- hooks: 3 different on-screen opening lines, max 7 words each, readable in one second, never invented facts.
  This format's hook {fmt_rule}. Score each honestly: clarity (reads at a glance), curiosity (makes you stay to
  see), emotion (makes you feel something). No clichés (wanderlust, vibes, paradise, breathtaking).
  {('Use a clearly different angle from: ' + '; '.join(chr(34) + h + chr(34) for h in av) + '.') if av else ''}
- cta: closing line, max 6 words, worth sending to a friend (e.g. "Send this to your road trip person").
- caption: 1-3 short natural lines that name the places in plain words (people search them) and end with ONE
  question the viewer can answer in a comment.
- hashtags: {min(6, int(style.get('caption', {}).get('hashtags', 6) or 6))} specific ones (places first), without #."""
    try:
        data = extract_json(backend.ask(prompt, None, max_tokens=900 + 14 * len(facts)))
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
    lines = {k: clean_line(str(data.get(k) or "").strip().strip('"')) for k in ("tease", "payoff", "title")
             if data.get(k) and not isinstance(data.get(k), list)}
    if isinstance(data.get("payoff"), list):
        lines["payoff"] = [clean_line(str(p).strip().strip('"')) for p in data["payoff"] if str(p).strip()]
    if isinstance(data.get("labels"), list):
        lines["labels"] = [str(x or "").strip() for x in data["labels"]]
    return {"hooks": hooks, "hook": hooks[0]["text"] if hooks else None, **lines,
            "hook_type": hooks[0]["type"] if hooks else None,
            "cta": clean_line(str(data.get("cta", ""))),
            "caption": true_caption(backend, str(data.get("caption", "")).strip(), facts),
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
