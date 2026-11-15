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
                     "speed": s.get("speed"), "panel": s.get("panel")})
    texts = [{"type": o.get("type"), "text": o.get("text"), "start": o.get("start"), "duration": o.get("duration")}
             for o in p.get("overlays") or [] if o.get("text")]
    cap = _side(plan, ".caption.txt")
    return {**reel_card(plan), "segments": segs, "texts": texts,
            "caption": Path(cap).read_text() if cap else "", "qa_report": read_json(Path(f"{_base(plan)}.qa.json")),
            "sound_sheet": _side(plan, ".sound.jpg"), "grade": _side(plan, ".grade.jpg")}


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
    if kind == "learn":
        name = re.sub(r"[^A-Za-z0-9_-]+", "-", s("name")).strip("-") or "mystyle"
        return ["learn", *items("refs"), "-n", name] + (["--add"] if b.get("add") else []), name
    if kind == "ask":
        return ["ask", s("request")], s("request")[:60]
    if kind == "find":
        keys = ("place", "people", "date_from", "date_to", "kinds", "text", "folders", "label")
        return find_args(**{k: b[k] for k in keys if b.get(k) not in (None, "", [])}), s("label") or s("place")
    if kind == "trips":
        return ["trips", "--", *items("folders")], "trips"
    if kind == "music":
        return ["music", s("url")], s("url")
    if kind == "qa":
        return ["qa", s("video")], Path(s("video")).name
    if kind == "analyze":
        return ["analyze", "--", *items("sources")], "analyse footage"
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
            if method == "GET":
                if path == "/api/status":
                    return self._json(status())
                if path == "/api/reels":
                    return self._json(list_reels())
                if path == "/api/reel":
                    return self._json(reel_detail(_plan(arg("plan"))))
                if path == "/api/styles":
                    return self._json(styles())
                if path == "/api/ai":
                    return self._json(ai_status())
                if path == "/api/looks":
                    from .grade import list_looks
                    return self._json([{"name": k, "description": v.get("desc", "")} for k, v in list_looks().items()])
                if path == "/api/candidates":
                    from .planedit import candidates
                    return self._json(candidates(_plan(arg("plan")), int(arg("top", "40"))))
                if path == "/api/jobs":
                    return self._json(jobs.recent(int(arg("n", "20"))))
                m = re.fullmatch(r"/api/jobs/([\w-]+)", path)
                if m:
                    st = jobs.status(m.group(1))
                    st["log"] = jobs.log_tail(m.group(1), int(arg("lines", "40")))
                    return self._json(st)
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
                if path == "/api/ai/test":
                    return self._json(ai_test(str(b.get("provider"))))
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
            return self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    def _file(self, path: Path):
        """A media file, with byte ranges so <video> can seek."""
        if not path.is_file() or not allowed(path):
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
    print(json.dumps({"url": url, "version": __version__}), flush=True)
    if watch_stdin:
        threading.Thread(target=_exit_with_parent, daemon=True).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
