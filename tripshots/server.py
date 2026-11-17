"""The desktop app's local API: `tripshots serve` answers JSON over HTTP on 127.0.0.1 only.

The app (desktop/) starts this process, reads the first stdout line ({"url": ..., "version": ...}) and sends the
token it chose with every request (`Authorization: Bearer <token>`, or `?t=<token>` for <video>/<img> sources, which
can't set headers). Long work runs as the same background jobs the MCP server uses (jobs.py), so the CLI, agents
and the app see one another's jobs and reels. Standard library only: the app opens in a fraction of a second, and
the heavy libraries load in the job processes, when a reel is made.

    tripshots serve [--port 0] [--token TOKEN]    # token from TRIPSHOTS_API_TOKEN when not given
"""
from __future__ import annotations

import hmac
import json
import mimetypes
import os
import re
import sys
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import __version__, jobs
from .config import HOME, list_styles, load_env
from .util import ReelError, read_json

SECRETS = ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "MINIMAX_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "OPENAI_API_KEY")
SETTINGS = ("TRIPSHOTS_BACKEND", "TRIPSHOTS_MODEL", "TRIPSHOTS_COOKIES_BROWSER", "TRIPSHOTS_ENCODER") + SECRETS
PLAIN = re.compile(r"^[^\x00-\x1f]{0,4000}$")


# ------------------------------------------------------------------ what the app shows
def reel_roots() -> list[Path]:
    """Folders reels are written to: the reels folder, the app's last one, and ~/.tripshots/reels."""
    st = read_json(HOME / "tui.json", {}) or {}
    roots = [os.environ.get("TRIPSHOTS_OUT"), st.get("out_dir"), str(HOME / "reels")]
    out: list[Path] = []
    for r in roots:
        if r and Path(r).expanduser().is_dir() and Path(r).expanduser().resolve() not in out:
            out.append(Path(r).expanduser().resolve())
    return out


def _base(plan: Path) -> Path:
    return plan.with_name(plan.name[:-len(".plan.json")])


def _side(plan: Path, ext: str) -> str | None:
    p = Path(f"{_base(plan)}{ext}")
    return str(p) if p.exists() else None


def reel_card(plan: Path) -> dict:
    """One reel as the gallery lists it."""
    p = read_json(plan, {}) or {}
    canvas = (p.get("frame") or {}).get("canvas") or [1080, 1920]
    mp4 = _side(plan, ".mp4")
    qa = read_json(Path(f"{_base(plan)}.qa.json"), {}) or {}
    return {"name": _base(plan).name, "folder": str(plan.parent), "plan": str(plan), "video": mp4,
            "upload": _side(plan, ".nomusic.mp4") or _side(plan, ".noaudio.mp4"), "cover": _side(plan, ".cover.jpg"),
            "storyboard": _side(plan, ".storyboard.jpg"), "rendered": bool(mp4),
            "duration": round(sum(float(s.get("dur", 0)) for s in p.get("segments") or []), 2),
            "width": canvas[0], "height": canvas[1], "style": p.get("style"),
            "recipe": (p.get("recipe") or {}).get("id"), "sound": (p.get("music") or {}).get("label"),
            "sound_url": (p.get("music") or {}).get("source_url"),
            "qa": {"passed": qa.get("passed"), "total": qa.get("total")} if qa else None,
            "stale": bool(mp4) and plan.stat().st_mtime > Path(mp4).stat().st_mtime + 1,  # edited since its render
            "modified": round((Path(mp4) if mp4 else plan).stat().st_mtime)}


def list_reels(limit: int = 400) -> list[dict]:
    seen, out = set(), []
    for root in reel_roots():
        for plan in root.rglob("*.plan.json"):
            if plan in seen or len(plan.relative_to(root).parts) > 4:
                continue
            seen.add(plan)
            try:
                out.append(reel_card(plan))
            except Exception:
                continue
    return sorted(out, key=lambda r: -r["modified"])[:limit]


def reel_detail(plan: Path) -> dict:
    """A reel with its timeline: every slot's time, role, shot (with its thumbnail), transition, and the words."""
    from .clippick import file_length
    from .planedit import _shots
    p = read_json(plan)
    shots = _shots(p)
    segs = []
    for i, s in enumerate(p["segments"]):
        sh = shots.get(s.get("shot_id")) or {}
        segs.append({"slot": i + 1, "start": round(float(s.get("out_start", 0)), 3), "dur": float(s["dur"]),
                     "role": s.get("role"), "shot_id": s.get("shot_id"), "kind": sh.get("kind") or s.get("kind"),
                     "thumb": sh.get("thumb"), "file": Path(sh.get("src") or s.get("src") or "").name,
                     "note": (sh.get("ai") or {}).get("note"), "transition": s.get("trans_out"),
                     "speed": s.get("speed"), "panel": s.get("panel"), "ramp": s.get("ramp"),
                     "in": s.get("in"), "clip": [0.0, file_length(shots, sh)] if sh.get("kind") == "video" else None,
                     "layout": s.get("layout"), "subject_x": s.get("subject_x"), "kb": s.get("kb"),
                     "trans_dur": s.get("trans_dur"), "adjust": s.get("adjust") or {},
                     "graded": bool(s.get("lut")) and not s.get("no_grade"), "no_grade": bool(s.get("no_grade")),
                     "light": s.get("grade_note"), "layers": s.get("layers") or [],
                     "backdrop": (s.get("backdrop") or {}).get("mode"), "people": bool(s.get("people")),
                     "stabilize": bool(s.get("stabilize")), "freeze": bool(s.get("freeze")),
                     "reverse": bool(s.get("reverse")), "effect": s.get("effect"), "log": s.get("log"),
                     "vibes": list(((sh.get("ai") or {}).get("vibes") or {}))[:3],
                     "size": (sh.get("ai") or {}).get("shot_size"), "angle": (sh.get("ai") or {}).get("angle"),
                     "keys": s.get("keys") or []})
    from .planedit import history, texts as plan_texts
    cap = _side(plan, ".caption.txt")
    music = p.get("music") or {}
    return {**reel_card(plan), "segments": segs, "texts": plan_texts(p),
            "text_defaults": text_defaults(p), "history": history(plan),
            "caption": Path(cap).read_text() if cap else "", "social": read_json(Path(f"{_base(plan)}.social.json")),
            "qa_report": read_json(Path(f"{_base(plan)}.qa.json")),
            "revised": read_json(Path(f"{_base(plan)}.revise.json")),  # what the last notes did (revise.py)
            "beats": [round(float(b), 3) for b in p.get("beats") or []],
            "music": {k: music.get(k) for k in ("start", "gain_db", "fade_out", "label")} if music.get("path") else None,
            "grading": {k: (p.get("grade") or {}).get(k) for k in ("look", "strength", "grain", "vignette", "why")},
            "beat_punch": (p.get("motion") or {}).get("beat_punch"),
            "sound_sheet": _side(plan, ".sound.jpg"), "grade": _side(plan, ".grade.jpg"),
            "draft": _draft(plan), "effects": p.get("effects"),
            "pips": [{"index": k + 1, **{x: q.get(x) for x in ("shot_id", "kind", "start", "dur", "x", "y", "scale", "thumb")}}
                     for k, q in enumerate(p.get("pips") or [])]}


def _draft(plan: Path) -> str | None:
    """The quick preview of the plan as it stands (render --draft), if one was made since the last edit."""
    f = Path(f"{_base(plan)}.draft.mp4")
    return str(f) if f.exists() and f.stat().st_mtime >= plan.stat().st_mtime else None


def text_defaults(p: dict) -> dict:
    """Each kind of text's lettering in this plan when a line has none of its own (the editor starts from it)."""
    from .typo import PRESETS
    tcfg = p.get("text") or {}
    preset = PRESETS.get(str(tcfg.get("preset", "bold")), PRESETS["bold"])
    out = {}
    for kind in ("hook", "location", "cta", "label", "text", "caption"):
        base = dict(preset.get("hook" if kind in ("text", "caption") else kind) or {})
        own = tcfg.get("hook" if kind == "text" else kind) or {}
        if own.get("font"):
            base.update({k: v for k, v in own.items() if k in ("font", "size", "uppercase", "color", "anim")})
        out[kind] = {k: base.get(k) for k in ("font", "size", "uppercase", "color", "anim", "position")}
    return out


def still(plan: Path, t: float, raw: bool = False, mask: str | None = None) -> Path:
    """The frame at t with the plan's text as it stands now (cached by the plan's state and the time)."""
    from .render import still as render_still
    from .util import short_hash
    d = HOME / "cache" / "stills"
    out = d / f"{short_hash(f'{plan.resolve()}|{plan.stat().st_mtime_ns}|{t:.2f}|{raw}|{mask}', 16)}.jpg"
    if not out.exists():
        d.mkdir(parents=True, exist_ok=True)
        for old in sorted(d.glob("*.jpg"), key=lambda f: f.stat().st_mtime)[:-200]:
            old.unlink(missing_ok=True)   # a few hundred recent frames is plenty
        from .nodes import REGIONS
        render_still(read_json(plan), t, out, raw=raw, mask=mask if mask in REGIONS else None)
    return out


def fx_thumb(plan: Path, slot: int, kind: str, fid: str) -> Path | None:
    """A small picture of a library item on the reel's own shots (the editor's pickers): a transition as three
    moments from this shot into the next, a shot effect on this shot's thumbnail."""
    from .planedit import _shots
    from .util import short_hash
    p = read_json(plan)
    segs = p.get("segments") or []
    if not segs:
        return None
    i = max(0, min(len(segs) - 1, int(slot) - 1))
    by_id = _shots(p)
    def thumb(k):
        sh = by_id.get(segs[k].get("shot_id")) or {}
        t = sh.get("thumb") or segs[k].get("thumb")
        return t if t and Path(t).exists() else None
    a, b = thumb(i), thumb(min(i + 1, len(segs) - 1))
    if not a or not b:
        return None
    d = HOME / "cache" / "fx"
    out = d / f"{short_hash(f'{a}|{b}|{kind}|{fid}|v1', 16)}.jpg"
    if out.exists():
        return out
    import cv2
    import numpy as np
    def load(f):
        im = cv2.cvtColor(cv2.imread(str(f)), cv2.COLOR_BGR2RGB)
        h, w = im.shape[:2]
        tw, th = 144, 256   # an upright window from the middle
        k = max(tw / w, th / h)
        im = cv2.resize(im, (int(w * k) + 1, int(h * k) + 1), interpolation=cv2.INTER_AREA)
        y, x = (im.shape[0] - th) // 2, (im.shape[1] - tw) // 2
        return np.ascontiguousarray(im[y:y + th, x:x + tw])
    A, B = load(a), load(b)
    if kind == "effect":
        from .vfx import EFFECTS, apply
        if fid not in EFFECTS:
            return None
        img = np.concatenate([A, apply(A, {"id": fid, "amount": 0.8}, 0.4, [0.4])], axis=1)
    else:
        from .motion import TRANSITIONS, apply_transition
        if fid not in TRANSITIONS:
            return None
        img = np.concatenate([apply_transition(fid, A, B, q) for q in (0.3, 0.5, 0.7)], axis=1)
    d.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), cv2.cvtColor(img, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 85])
    return out


def look_thumb(plan: Path, slot: int, look: str) -> Path | None:
    """A small picture of one shot in a look (the editor's look strip): its thumbnail through the LUT that look would
    give it, with the colourist's cached notes for that shot. No AI calls."""
    from . import grade
    from .planedit import _shots
    from .util import short_hash
    p = read_json(plan)
    segs = p.get("segments") or []
    seg = segs[max(0, min(len(segs) - 1, int(slot) - 1))] if segs else {}
    shot = _shots(p).get(seg.get("shot_id")) or {}
    thumb = shot.get("thumb") or seg.get("thumb")
    if not thumb or not Path(thumb).exists():
        return None
    strength = float((p.get("grade") or {}).get("strength") or 0.75)
    d = HOME / "cache" / "looks"
    out = d / f"{short_hash(f'{thumb}|{look}|{strength:.2f}|g1', 16)}.jpg"
    if out.exists():
        return out
    import cv2
    im = cv2.imread(str(thumb))
    if im is None:
        return None
    h = 240
    im = cv2.resize(im, (max(1, int(im.shape[1] * h / im.shape[0])), h), interpolation=cv2.INTER_AREA)
    rgb = cv2.cvtColor(im, cv2.COLOR_BGR2RGB)
    lk = grade.get_look(look) if look not in ("none", "off", "") else None
    if lk:
        stats = grade.shot_stats(shot)
        notes, _ = grade.ai_notes([shot], {shot["id"]: stats}, None, Path(p.get("work") or "."), False)
        n = notes.get(shot["id"]) or {}
        lut = grade.shot_lut(stats, lk, strength, {**{k: n.get(k) for k in ("exposure", "wb", "keep_mood")},
                                                   **({"match": lk["match"]} if lk.get("match") else {})})
        rgb = grade.apply_cube(rgb, lut)
    d.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 86])
    return out


def fonts() -> list[dict]:
    """Fonts a line can be set in: the bundled faces, then the open-font library (fetched on first use)."""
    from . import fontlib
    from .typo import FONTS
    out = [{"id": n, "label": n.replace("-", " ").title(), "look": "bundled", "weight": w or 400, "bundled": True}
           for n, (_f, w) in FONTS.items()]
    for fam, (look, weights, scripts) in fontlib.CATALOG.items():
        for w in weights:
            out.append({"id": fontlib.name(fam, w), "label": f"{fam} {w}", "look": look, "weight": w,
                        "bundled": False, "fetched": fontlib.path(fam, w).exists(), "scripts": list(scripts)})
    return out


def font_file(name: str) -> Path | None:
    from . import fontlib
    from .typo import FONT_DIR, FONTS
    if name.lower() in FONTS:
        return FONT_DIR / FONTS[name.lower()][0]
    fam = fontlib.parse(name)
    if fam and fam[0] in fontlib.CATALOG:
        return fontlib.get(*fam)
    return None


def styles() -> list[dict]:
    from .config import load_style
    out = []
    for n, path in sorted(list_styles().items()):
        try:
            st = load_style(n)
        except Exception:
            st = {}
        out.append({"name": n, "description": st.get("description", ""), "user": HOME in Path(path).parents,
                    "references": len(st.get("learned_from") or []), "recipes": len(st.get("recipes") or [])})
    return out


def status() -> dict:
    from . import catalog
    from .util import which
    music = [m for m in os.environ.get("TRIPSHOTS_MUSIC", "").split(os.pathsep) if m.strip()]
    return {"version": __version__, "home": str(HOME), "frozen": bool(getattr(sys, "frozen", False)),
            "engine": jobs.engine_command()[0], "footage_folders": [str(p) for p in catalog.footage_roots()],
            "reels_folder": os.environ.get("TRIPSHOTS_OUT"), "music_folders": music,
            "ffmpeg": bool(which("ffmpeg")), "settings": {k: _shown(k) for k in SETTINGS},
            "styles": sorted(list_styles()), "recent_jobs": jobs.recent(8)}


def _shown(key: str):
    """A setting as the app may show it: secrets only as set/unset, and anything that looks like a key masked
    (a key pasted into the wrong field must not come back in plain text)."""
    v = os.environ.get(key)
    if key in SECRETS:
        return bool(v)
    if v and re.match(r"^(sk-|AIza|ghp_|xox)", v) or (v and len(v) > 40 and " " not in v):
        return "(hidden: looks like a key)"
    return v


def save_settings(body: dict) -> dict:
    from . import catalog
    from .config import write_env
    if "footage_folders" in body:
        catalog.set_footage_roots([str(f) for f in body["footage_folders"] or []])
    upd = {}
    if body.get("reels_folder"):
        upd["TRIPSHOTS_OUT"] = str(Path(body["reels_folder"]).expanduser())
    if "music_folders" in body:
        upd["TRIPSHOTS_MUSIC"] = os.pathsep.join(str(Path(m).expanduser()) for m in body["music_folders"] or [])
    for k, v in (body.get("env") or {}).items():
        if k in SETTINGS and isinstance(v, str) and PLAIN.match(v):
            upd[k] = v.strip()
    if body.get("backend") in BACKENDS:
        upd["TRIPSHOTS_BACKEND"] = body["backend"]
    if upd:
        write_env(upd)  # (an empty value removes the setting)
    return status()


# ------------------------------------------------------------------ AI setup
BACKENDS = ("auto", "claude-cli", "minimax", "api", "none")
PING = "Reply with the single word OK."


def ai_status() -> dict:
    """What the app's AI page shows: each AI, whether it's ready, and which one makes the creative calls now.
    Local checks only (`claude auth status` reads the saved login, nothing is sent)."""
    from .ai import ClaudeCLI
    from .util import which
    claude = which("claude")
    login = ClaudeCLI.login_status() if claude else None
    token = bool(os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"))
    if not claude:
        c_state = "missing"
    elif token or (login or {}).get("loggedIn") or login is None:
        c_state = "ready"
    else:
        c_state = "logged_out"
    try:
        import google.genai  # noqa: F401
        sdk = True
    except ImportError:
        sdk = False
    gem_key = bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
    providers = {
        "claude": {"state": c_state, "path": claude, "account": (login or {}).get("email") or (login or {}).get("account"),
                   "plan": (login or {}).get("subscriptionType") or (login or {}).get("plan"), "token": token},
        "minimax": {"state": "ready" if os.environ.get("MINIMAX_API_KEY") else "no_key",
                    "model": os.environ.get("TRIPSHOTS_MINIMAX_MODEL") or "MiniMax-M3"},
        "anthropic": {"state": "ready" if os.environ.get("ANTHROPIC_API_KEY") else "no_key"},
        "gemini": {"state": "ready" if gem_key and sdk else ("no_sdk" if gem_key else "no_key"),
                   "model": os.environ.get("TRIPSHOTS_GEMINI_MODEL") or "gemini-flash-latest"},
    }
    backend = (os.environ.get("TRIPSHOTS_BACKEND") or "auto").lower()
    order = [n for n, ok in (("claude-cli", c_state == "ready"), ("minimax", providers["minimax"]["state"] == "ready"),
                             ("api", providers["anthropic"]["state"] == "ready")) if ok]
    using = None if backend == "none" else (order[0] if backend == "auto" and order else
                                            backend if backend in order else None)
    return {"backend": backend, "order": order, "using": using, "providers": providers}


def ai_test(provider: str) -> dict:
    """Send one tiny request to an AI to prove the login or key works: {"ok", "message"}."""
    import time
    t = time.time()
    try:
        if provider == "gemini":
            from .watch import api_key
            from google import genai
            names = [m.name for m in genai.Client(api_key=api_key()).models.list()]
            flash = [n for n in names if "flash" in n]
            return {"ok": True, "message": f"Gemini answered: {len(names)} models available to this key"
                                           + (f", including {flash[0].split('/')[-1]}" if flash else "")}
        from .ai import AnthropicAPI, ClaudeCLI, _minimax
        be = {"claude": ClaudeCLI, "minimax": _minimax, "anthropic": AnthropicAPI}.get(provider)
        if be is None:
            raise ReelError(f"unknown AI: {provider}")
        reply = be().ask(PING, max_tokens=16).strip()
        return {"ok": True, "message": f"{provider} answered in {time.time() - t:.0f} s: {reply[:40]}"}
    except Exception as e:
        return {"ok": False, "message": " ".join(str(e).split())[:400] or type(e).__name__}


# ------------------------------------------------------------------ jobs the app can start
def job_args(kind: str, b: dict) -> tuple[list[str], str]:
    """(CLI arguments, label) for a job request; only these kinds, built from typed fields."""
    from .commands import MAKE_FLAGS, find_args, make_args

    def s(key, default=""):
        v = b.get(key, default)
        return str(v) if v is not None else default

    def items(key):
        return [str(x) for x in b.get(key) or [] if str(x).strip()]

    if kind == "make":
        opts = {k: b.get(k) for k, _ in MAKE_FLAGS}
        return make_args(items("sources"), variants=int(b.get("variants") or 1), upload_copy=bool(b.get("upload_copy")),
                         no_location=bool(b.get("no_location")), dry_run=bool(b.get("dry_run", False)),
                         name=b.get("name") or None, **opts), b.get("name") or "new reel"
    if kind == "render":
        return ["render", str(_plan(s("plan")))], Path(s("plan")).name
    if kind == "carousel":   # a carousel post from the reel (carousel.py)
        args = ["carousel", str(_plan(s("plan"))), "-n", str(max(3, min(10, int(b.get("slides") or 8))))]
        if b.get("title"):
            args += ["--title", s("title")]
        if b.get("handle"):
            args += ["--handle", s("handle")]
        if b.get("route") is False:
            args.append("--no-route")
        return args, Path(s("plan")).name
    if kind == "preview":   # the editor's motion preview of unrendered edits (render --draft)
        return ["render", str(_plan(s("plan"))), "--draft"], Path(s("plan")).name
    if kind == "learn":
        name = re.sub(r"[^A-Za-z0-9_-]+", "-", s("name")).strip("-") or "mystyle"
        return ["learn", *items("refs"), "-n", name] + (["--add"] if b.get("add") else []), name
    if kind == "ask":  # the app asks for a finished reel; plan_only for a storyboard first
        return ["ask", s("request")] + ([] if b.get("plan_only") else ["--render"]), s("request")[:60]
    if kind == "find":
        keys = ("place", "people", "date_from", "date_to", "kinds", "text", "folders", "label", "camera")
        return find_args(**{k: b[k] for k in keys if b.get(k) not in (None, "", [])}), s("label") or s("place")
    if kind == "trips":
        return ["trips", "--", *items("folders")], "trips"
    if kind == "split":   # one trip in parts, a reel from each (projects in the trip's collection)
        args = ["split-trip"] + ([s("trip")] if b.get("trip") else []) + ["--by", "place" if b.get("by") == "place" else "day", "--make"]
        if b.get("plan_only"):
            args.append("--plan-only")
        for k, flag in (("style", "-s"), ("music", "-m")):
            if b.get(k):
                args += [flag, s(k)]
        if items("folders"):
            args += ["--folders", *items("folders")]
        return args, f"Split {s('trip') or 'trip'}"
    if kind == "music":
        return ["music", s("url")], s("url")
    if kind == "looks":   # the look library: fetch a free pack, add LUT files, remove a pack or a look
        act = s("action")
        if act == "fetch":
            from .luts import PACKS
            if s("pack") not in PACKS:
                raise ReelError(f"unknown pack {s('pack')}")
            return ["looks", "fetch", s("pack")], f"Looks: {PACKS[s('pack')]['title']}"
        if act == "add":
            files = items("files")
            if not files:
                raise ReelError("choose LUT files")
            return ["looks", "add", *files], "Add looks"
        if act == "remove":
            return ["looks", "remove"] + ([s("name")] if b.get("name") else []) + \
                (["--pack", s("pack")] if b.get("pack") else []), "Remove looks"
        raise ReelError("looks: fetch, add or remove")
    if kind == "caption":
        return ["caption", str(_plan(s("plan")))] + (["--tone", s("tone")] if b.get("tone") else []) + \
            (["--extra", s("extra")] if b.get("extra") else []), Path(s("plan")).name
    if kind == "qa":
        return ["qa", s("video")], Path(s("video")).name
    if kind == "revise":  # notes pinned to moments of the finished reel -> edits, rendered again
        notes = [{"t": round(float(n.get("t", 0)), 3), "text": str(n.get("text", ""))[:300]}
                 for n in (b.get("notes") or [])[:30] if isinstance(n, dict) and str(n.get("text", "")).strip()]
        if not notes:
            raise ReelError("no notes")
        return ["revise", str(_plan(s("plan"))), "--notes-json", json.dumps(notes)], Path(s("plan")).name
    if kind == "analyze":   # the catalogue: new files only, unless asked to look at every shot again
        flags = (["--rescore"] if b.get("rescore") else []) + (["--no-ai"] if b.get("no_ai") else []) + \
            (["--no-details"] if b.get("no_details") else [])
        return ["analyze", *flags, "--", *items("sources")], "analyse footage"
    if kind == "discover":
        return ["people", "discover", "--", *items("folders")], "people"
    raise ReelError(f"unknown job kind: {kind}")


def _plan(path: str) -> Path:
    p = Path(path).expanduser()
    if not p.name.endswith(".plan.json") or not p.is_file():
        raise ReelError(f"not a TripShots plan file: {path}")
    return p


# ------------------------------------------------------------------ files
def allowed(path: Path) -> bool:
    """Media the app may show: TripShots' own files, reels, footage and music folders. Nothing else."""
    from . import catalog
    try:
        rp = path.expanduser().resolve()
    except OSError:
        return False
    roots = [HOME, *reel_roots(), *catalog.footage_roots()] + \
        [Path(m) for m in os.environ.get("TRIPSHOTS_MUSIC", "").split(os.pathsep) if m.strip()]
    for r in roots:
        try:
            rp.relative_to(Path(r).expanduser().resolve())
            return True
        except (ValueError, OSError):
            continue
    return False


def telemetry_post(b: dict) -> dict:
    """The window's side of telemetry: the user's answer, a new id, its events (views, editor tools) and crashes."""
    from . import telemetry
    if "consent" in b:
        return telemetry.set_consent(bool(b["consent"]))
    if b.get("action") == "reset":
        return telemetry.reset_id()
    if b.get("action") == "send":
        return telemetry.flush(force=True)
    n = 0
    for ev in list(b.get("events") or [])[:50]:
        if isinstance(ev, dict) and isinstance(ev.get("props", {}), dict):
            n += telemetry.record(str(ev.get("name")), **(ev.get("props") or {}))
    if isinstance(b.get("crash"), dict):
        telemetry.outside_crash(b["crash"], "ui")
    return {"recorded": n}


# ------------------------------------------------------------------ HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = f"tripshots/{__version__}"
    token = ""

    def log_message(self, fmt, *args):  # quiet: the app shows what matters
        pass

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, Range")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Expose-Headers", "Content-Range, Accept-Ranges, Content-Length")

    def _json(self, obj, code=200):
        data = json.dumps(obj, default=str).encode()
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _authed(self, q) -> bool:
        got = self.headers.get("Authorization", "")
        got = got[7:] if got.startswith("Bearer ") else (q.get("t") or [""])[0]
        return bool(self.token) and hmac.compare_digest(got.encode(), self.token.encode())

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        self._route("GET")

    def do_POST(self):
        self._route("POST")

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        b = json.loads(self.rfile.read(min(n, 2_000_000)) or b"{}")
        return b if isinstance(b, dict) else {}

    def _route(self, method):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if not self._authed(q):
            return self._json({"error": "unauthorized"}, 401)
        arg = (lambda k, d="": (q.get(k) or [d])[0])
        try:
            path = u.path.rstrip("/")
            if path == "/api/health":
                return self._json({"ok": True, "version": __version__})
            if path == "/api/file" and method == "GET":
                return self._file(Path(arg("path")))
            if path == "/api/font" and method == "GET":
                f = font_file(arg("name"))
                return self._file(f, trusted=True) if f else self._json({"error": "no such font"}, 404)
            if method == "GET":
                if path == "/api/status":
                    return self._json(status())
                if path == "/api/reels":
                    from .projects import annotate
                    return self._json(annotate(list_reels()))
                if path == "/api/carousel":   # the reel's carousel as made and edited (carousel.json), or null
                    from .carousel import load
                    return self._json(load(_plan(arg("plan"))))
                if path == "/api/collections":
                    from .projects import collections
                    return self._json(collections())
                if path == "/api/reel":
                    return self._json(reel_detail(_plan(arg("plan"))))
                if path == "/api/still":
                    return self._file(still(_plan(arg("plan")), float(arg("at", "0")), arg("raw") == "1", arg("mask") or None),
                                      trusted=True)
                if path == "/api/lookthumb":
                    f = look_thumb(_plan(arg("plan")), int(arg("slot", "1")), arg("look", "none"))
                    return self._file(f, trusted=True) if f else self._json({"error": "no picture"}, 404)
                if path == "/api/fonts":
                    return self._json(fonts())
                if path == "/api/effects":   # the effects library (fxlib.py; no numpy needed)
                    from .fxlib import catalog
                    return self._json(catalog())
                if path == "/api/fxthumb":   # one transition or shot effect, drawn on this reel's own shots
                    f = fx_thumb(_plan(arg("plan")), int(arg("slot", "1")), arg("kind", "transition"), arg("id", ""))
                    return self._file(f, trusted=True) if f else self._json({"error": "no picture"}, 404)
                if path == "/api/styles":
                    return self._json(styles())
                if path == "/api/ai":
                    return self._json(ai_status())
                if path == "/api/looks":
                    from .grade import list_looks
                    return self._json([{"name": k, "title": v.get("title"), "description": v.get("desc", ""),
                                        "builtin": v.get("builtin", False), "pack": v.get("pack"),
                                        "lut": bool(v.get("cube")), "tags": v.get("tags") or [],
                                        "for_log": bool((v.get("profile") or {}).get("log_input"))}
                                       for k, v in list_looks().items()])
                if path == "/api/lookpacks":
                    from .luts import packs
                    return self._json(packs())
                if path == "/api/candidates":
                    from .planedit import candidates
                    return self._json(candidates(_plan(arg("plan")), int(arg("top", "40"))))
                if path == "/api/shots":   # every shot of the reel's footage, searched and paged (clippick.py)
                    from .clippick import browse
                    return self._json(browse(_plan(arg("plan")), arg("q", ""), arg("kind", "all"), arg("sort", "best"),
                                             int(arg("offset", "0")), int(arg("limit", "60")), arg("group", "1") == "1"))
                if path == "/api/clip":   # a long clip for the trim step: its length, a strip of its frames
                    from .clippick import clip
                    slot = arg("slot")
                    return self._json(clip(_plan(arg("plan")), arg("shot"), int(slot) if slot else None,
                                           float(arg("dur")) if arg("dur") else None))
                if path == "/api/clip/play":   # the chosen part of a clip, small enough for the app's player
                    from .clippick import window
                    return self._file(window(_plan(arg("plan")), arg("shot"), float(arg("at", "0")),
                                             float(arg("need", "1"))), trusted=True)
                if path == "/api/jobs":
                    return self._json(jobs.recent(int(arg("n", "20"))))
                m = re.fullmatch(r"/api/jobs/([\w-]+)", path)
                if m:
                    st = jobs.status(m.group(1))
                    st["log"] = jobs.log_tail(m.group(1), int(arg("lines", "40")))
                    return self._json(st)
                if path == "/api/telemetry":   # the user's answer, what was sent, what is waiting
                    from . import telemetry
                    return self._json({**telemetry.status(), "sent": telemetry.sent_log(int(arg("n", "30"))),
                                       "errors": telemetry.recent_errors(5)})
                if path == "/api/report":   # exactly what Report a problem would send, before it is sent
                    from . import telemetry
                    return self._json(telemetry.report_payload(arg("message"), arg("email"), arg("diagnostics", "1") == "1"))
                if path == "/api/selection":
                    from . import catalog
                    sel = catalog.load_selection(arg("id"))
                    return self._json({"summary": sel["summary"], "query": sel["query"], "count": len(sel["files"]),
                                       "files": [{k: f.get(k) for k in ("path", "kind", "created", "place")}
                                                 for f in sel["files"][:200]]})
            else:
                b = self._body()
                if path == "/api/settings":
                    return self._json(save_settings(b))
                if path == "/api/jobs":
                    args, label = job_args(str(b.get("kind")), b)
                    jid = jobs.start(args, str(b.get("kind")), label)
                    return self._json(jobs.status(jid))
                m = re.fullmatch(r"/api/jobs/([\w-]+)/cancel", path)
                if m:
                    return self._json(jobs.cancel(m.group(1)))
                if path == "/api/edit":
                    from .planedit import apply
                    return self._json(apply(_plan(str(b.get("plan"))), list(b.get("edits") or [])))
                if path == "/api/carousel":   # edit the carousel (only the changed slides are drawn again)
                    from .carousel import edit
                    return self._json(edit(_plan(str(b.get("plan"))), list(b.get("ops") or [])))
                if path == "/api/collections":   # add, rename or remove a collection (projects.py)
                    from .projects import collection
                    return self._json(collection(str(b.get("action")), str(b.get("name") or ""), b.get("to")))
                if path == "/api/reel/manage":   # pin, favorite, collection, rename, duplicate, delete (projects.py)
                    from .projects import manage
                    return self._json(manage(_plan(str(b.get("plan"))), str(b.get("action")), b.get("value")))
                if path in ("/api/undo", "/api/redo"):
                    from .planedit import step
                    return self._json(step(_plan(str(b.get("plan"))), back=path == "/api/undo"))
                if path == "/api/telemetry":   # consent, a new id, events and crashes from the window
                    return self._json(telemetry_post(b))
                if path == "/api/report":
                    from . import telemetry
                    return self._json(telemetry.send_report(str(b.get("message") or ""), str(b.get("email") or ""),
                                                            bool(b.get("diagnostics", True))))
                if path == "/api/ai/test":
                    return self._json(ai_test(str(b.get("provider"))))
                if path == "/api/clip/ai":   # the AI chooses which part of the clip plays in the slot
                    from .clippick import ai_window
                    slot = b.get("slot")
                    return self._json(ai_window(_plan(str(b.get("plan"))), str(b.get("shot")),
                                                int(slot) if slot else None,
                                                float(b["dur"]) if b.get("dur") else None))
                if path == "/api/caption":
                    plan = _plan(str(b.get("plan")))
                    Path(f"{_base(plan)}.caption.txt").write_text(str(b.get("text") or ""))
                    return self._json({"ok": True})
            return self._json({"error": f"no such endpoint: {method} {u.path}"}, 404)
        except ReelError as e:
            return self._json({"error": str(e)}, 400)
        except (BrokenPipeError, ConnectionResetError):
            return None
        except Exception as e:  # the app shows it; the server keeps running
            try:
                from . import telemetry
                telemetry.crash(e, f"api:{u.path}")
            except Exception:
                pass
            return self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    def _file(self, path: Path, trusted: bool = False):
        """A media file, with byte ranges so <video> can seek."""
        if not path.is_file() or not (trusted or allowed(path)):
            return self._json({"error": "not found"}, 404)
        size = path.stat().st_size
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        rng = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range", "").strip())
        start, end = 0, size - 1
        if rng and (rng.group(1) or rng.group(2)):
            if rng.group(1):
                start = int(rng.group(1))
                end = min(int(rng.group(2)), size - 1) if rng.group(2) else size - 1
            else:
                start = max(0, size - int(rng.group(2)))
            if start > end:
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", f"bytes */{size}")
                self._cors()
                self.end_headers()
                return
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self._cors()
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        with open(path, "rb") as f:
            f.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = f.read(min(1 << 20, left))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return
                left -= len(chunk)


def _exit_with_parent():
    """The app holds our stdin open; when it goes away (quit, crash), so does this server."""
    try:
        while sys.stdin.read(1):
            pass
    except Exception:
        pass
    os._exit(0)


def serve(port: int = 0, token: str | None = None, watch_stdin: bool = False) -> None:
    load_env()
    from .commands import default_out
    default_out()
    Handler.token = token or os.environ.get("TRIPSHOTS_API_TOKEN") or ""
    if not Handler.token:
        raise ReelError("serve needs a token: --token or TRIPSHOTS_API_TOKEN")
    httpd = ThreadingHTTPServer(("127.0.0.1", int(port)), Handler)
    httpd.daemon_threads = True
    url = f"http://127.0.0.1:{httpd.server_address[1]}"
    from . import telemetry
    os.environ.setdefault("TRIPSHOTS_VIA", "app")   # the jobs it starts count as the app's
    telemetry.start_background()
    print(json.dumps({"url": url, "version": __version__}), flush=True)
    if watch_stdin:
        threading.Thread(target=_exit_with_parent, daemon=True).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
