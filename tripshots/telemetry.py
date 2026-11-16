"""Anonymous usage counts and crash reports, sent only after the user says yes.

What is sent (docs/privacy.md has the full list): a random install id made on this computer (not tied to the
user, and they can reset it), the app version, the OS name, version and chip, and small named events: which
command or screen was used, whether it worked and roughly how long it took, which editor tool was used. A crash
sends the error's type, where in TripShots it happened, and its message with paths, file names, e-mail addresses,
links and long ids removed.

Never sent: footage, pictures, sound, file or folder names, paths, places, people, text typed into a reel, captions,
AI keys, or the IP address (the collector keeps only the country Cloudflare reports).

Nothing leaves the computer while the answer is unknown or no, under DO_NOT_TRACK=1 or TRIPSHOTS_TELEMETRY=off, or
when no collector is set (development builds). Every batch that is sent is also written to
~/.tripshots/telemetry/sent.jsonl, which Settings shows. Standard library only (server.py imports this).

    tripshots telemetry status|on|off|log|reset|send
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path
from urllib import request

from . import __version__
from .config import HOME

ENDPOINT = ""   # the collector; release builds stamp it (tools/set_version.py --telemetry URL)
STATE = HOME / "telemetry.json"
DIR = HOME / "telemetry"
QUEUE, SENT, ERRORS, PENDING = DIR / "queue.jsonl", DIR / "sent.jsonl", DIR / "errors.jsonl", DIR / "pending"
ISSUES = "https://github.com/abelkuruvilla/tripshots/issues/new"
MAX_QUEUE, MAX_SENT, MAX_ERRORS, BATCH = 2000, 400, 50, 200
FLUSH_EVERY = 6 * 3600   # a command-line run sends at most this often; the app's server sends every 15 minutes

# event -> the properties it may carry. The collector checks the same list (telemetry/worker/src/validate.js)
EVENTS = {
    "app_open": {"app"},
    "command": {"cmd", "ok", "secs", "via", "flags", "error"},
    "view": {"view"},
    "edit": {"op", "n"},
    "feature": {"name", "kind"},
    "consent": {"on"},
}
WORD = re.compile(r"^[A-Za-z0-9_.:+\-]{0,48}$")
SECS = (1, 3, 10, 30, 60, 180, 600, 1800, 3600)
_session = uuid.uuid4().hex[:12]
_lock = threading.Lock()


# ------------------------------------------------------------------ consent and identity
def _state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def _save(st: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, indent=1))


def endpoint() -> str:
    return (os.environ.get("TRIPSHOTS_TELEMETRY_URL") or ENDPOINT).rstrip("/")


def blocked() -> str | None:
    """Why nothing may be sent whatever the user said, or None."""
    if os.environ.get("DO_NOT_TRACK", "").strip() not in ("", "0"):
        return "DO_NOT_TRACK is set"
    if os.environ.get("TRIPSHOTS_TELEMETRY", "").lower() in ("0", "off", "no", "false"):
        return "TRIPSHOTS_TELEMETRY is off"
    if not endpoint():
        return "no collector is set up in this build"
    return None


def consent() -> bool | None:
    return _state().get("consent")


def enabled() -> bool:
    return consent() is True and blocked() is None


def install_id() -> str:
    st = _state()
    if not st.get("id"):
        st["id"] = uuid.uuid4().hex
        _save(st)
    return st["id"]


def set_consent(on: bool) -> dict:
    st = _state()
    st.update({"consent": bool(on), "asked": int(time.time())})
    st.setdefault("id", uuid.uuid4().hex)
    _save(st)
    if not on:   # a no also drops what was waiting
        for p in (QUEUE,):
            p.unlink(missing_ok=True)
    else:
        record("consent", on=True)
    return status()


def reset_id() -> dict:
    """A new random id: what was sent before can't be linked to what is sent from now on."""
    st = _state()
    st["id"] = uuid.uuid4().hex
    _save(st)
    QUEUE.unlink(missing_ok=True)
    return status()


def status() -> dict:
    st = _state()
    return {"consent": st.get("consent"), "asked": st.get("asked"), "id": (st.get("id") or "")[:8],
            "blocked": blocked(), "endpoint": bool(endpoint()), "queued": _count(QUEUE),
            "last_sent": st.get("last_sent"), "can_report": bool(endpoint())}


# ------------------------------------------------------------------ events
def context() -> dict:
    """Who is sending, coarsely: never more than this."""
    osv = platform.mac_ver()[0] if sys.platform == "darwin" else platform.release()
    return {"install": install_id(), "session": _session, "v": __version__, "os": sys.platform,
            "osv": ".".join(osv.split(".")[:2])[:16], "arch": platform.machine().lower()[:16],
            "frozen": bool(getattr(sys, "frozen", False))}


def clean_props(name: str, props: dict) -> dict | None:
    """Only the properties this event may carry, only plain words, numbers and yes/no."""
    allowed = EVENTS.get(name)
    if allowed is None:
        return None
    out = {}
    for k, v in props.items():
        if k not in allowed or v is None:
            continue
        if isinstance(v, bool) or (isinstance(v, (int, float)) and abs(v) < 1e9):
            out[k] = v
        elif isinstance(v, str) and WORD.match(v):
            out[k] = v
        elif isinstance(v, (list, tuple)):
            words = [x for x in v if isinstance(x, str) and WORD.match(x)][:30]
            if words:
                out[k] = words
    return out


def bucket(secs: float) -> int:
    """How long, roughly: 1, 3, 10, 30 s, 1, 3, 10, 30 min, 1 h."""
    return next((b for b in SECS if secs <= b), SECS[-1])


def record(name: str, **props) -> bool:
    if not enabled():
        return False
    p = clean_props(name, props)
    if p is None:
        return False
    ev = {"name": name, "props": p, "ts": int(time.time()), **context()}
    _append(QUEUE, ev, MAX_QUEUE)
    return True


# ------------------------------------------------------------------ crashes
HOME_DIR = str(Path.home())
_PKG = str(Path(__file__).resolve().parent).replace("\\", "/")
_SCRUB = [
    (re.compile(r"https?://\S+"), "<link>"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "<email>"),
    (re.compile(r"(?:[A-Za-z]:\\|\\\\)[^\s'\"<>|]*"), "<path>"),
    (re.compile(r"(?<!\w)(?:~|\.{1,2})?/(?:[^\s'\"<>:/]+/)*[^\s'\"<>:/]*"), "<path>"),
    (re.compile(r"\b[\w-]+\.(?:mp4|mov|m4v|avi|mkv|insv|jpe?g|png|heic|heif|dng|arw|cr\d|nef|raf|tiff?|webp|gif|"
                r"mp3|m4a|wav|aac|flac|aiff?|json|ya?ml|cube|srt|txt|lrf)\b", re.I), "<file>"),
    (re.compile(r"\b[A-Za-z0-9_\-]{24,}\b"), "<id>"),
]


def scrub(text: str, limit: int = 300) -> str:
    """An error message without the user's paths, file names, addresses, links or keys."""
    s = str(text or "").replace(HOME_DIR, "~")
    for pat, rep in _SCRUB:
        s = pat.sub(rep, s)
    s = re.sub(r"(<path>)(\s*<path>)+", r"\1", s)
    return s[:limit]


def frames(tb) -> list[str]:
    """Where it happened, as tripshots/module.py:function:line; frames outside TripShots become their module name."""
    out = []
    for f in traceback.extract_tb(tb)[-12:]:
        fn = f.filename.replace("\\", "/")
        rel = fn[len(_PKG) + 1:] if fn.startswith(_PKG + "/") else fn[10:] if fn.startswith("tripshots/") else None
        if rel is not None:   # this package (a frozen engine names its files tripshots/x.py)
            out.append(f"tripshots/{rel}:{f.name}:{f.lineno}")
        else:
            mod = Path(fn).stem
            if not out or out[-1] != f"<{mod}>":
                out.append(f"<{mod}>")
    return out


def fingerprint(kind: str, etype: str, frs: list[str]) -> str:
    """Same bug, same group, across versions: the type and the TripShots functions, without line numbers."""
    own = [re.sub(r":\d+$", "", f) for f in frs if not f.startswith("<")][-5:]
    return hashlib.sha1(f"{kind}|{etype}|{'|'.join(own)}".encode()).hexdigest()[:16]


def crash(exc: BaseException, where: str, kind: str = "engine", handled: bool = False) -> dict:
    """Note an error: always in the local list (Report a problem can attach it), sent only with consent."""
    etype = type(exc).__name__
    frs = frames(exc.__traceback__)
    c = {"kind": kind, "type": etype[:60], "message": scrub(str(exc)), "where": scrub(where, 80),
         "frames": frs, "handled": bool(handled), "fingerprint": fingerprint(kind, etype, frs), "ts": int(time.time())}
    try:
        _append(ERRORS, c, MAX_ERRORS)
        if enabled():
            _append(QUEUE, {"name": "crash", "crash": c, "ts": c["ts"], **context()}, MAX_QUEUE)
    except OSError:
        pass
    return c


def outside_crash(c: dict, kind: str) -> dict | None:
    """A crash the app's window or shell reports (JavaScript, Rust): cleaned the same way."""
    if not isinstance(c, dict):
        return None
    etype = str(c.get("type") or "Error")[:60]
    frs = [scrub(re.sub(r"\(?(?:https?|tauri|asset)://[^/\s]+/", "", str(f)), 120) for f in (c.get("frames") or [])][:12]
    out = {"kind": kind, "type": re.sub(r"[^\w.]", "", etype) or "Error", "message": scrub(c.get("message") or ""),
           "where": scrub(str(c.get("where") or ""), 80), "frames": frs, "handled": bool(c.get("handled")),
           "fingerprint": fingerprint(kind, etype, frs), "ts": int(time.time())}
    try:
        _append(ERRORS, out, MAX_ERRORS)
        if enabled():
            _append(QUEUE, {"name": "crash", "crash": out, "ts": out["ts"], **context()}, MAX_QUEUE)
    except OSError:
        pass
    return out


def pick_up_pending() -> int:
    """Crash notes the desktop shell left (a panic, an engine that wouldn't start), sent with the next batch."""
    if not PENDING.is_dir():
        return 0
    n = 0
    for f in sorted(PENDING.glob("*.json"))[:20]:
        try:
            outside_crash(json.loads(f.read_text()), "shell")
            n += 1
        except (OSError, ValueError):
            pass
        f.unlink(missing_ok=True)
    return n


def recent_errors(n: int = 10) -> list[dict]:
    return _read(ERRORS)[-n:]


# ------------------------------------------------------------------ bug reports
def report_payload(message: str, email: str = "", diagnostics: bool = True) -> dict:
    """Exactly what Report a problem sends: shown to the user before it goes."""
    out = {"message": str(message or "").strip()[:4000], "email": str(email or "").strip()[:120] or None,
           "install": install_id(), "v": __version__}
    if diagnostics:
        ctx = context()
        out["diagnostics"] = {"os": ctx["os"], "osv": ctx["osv"], "arch": ctx["arch"], "frozen": ctx["frozen"],
                              "errors": [{k: e.get(k) for k in ("kind", "type", "message", "where", "frames", "ts")}
                                         for e in recent_errors(5)],
                              "jobs": _recent_jobs()}
    return out


def _recent_jobs() -> list[dict]:
    try:
        from . import jobs
        return [{"kind": j.get("kind"), "state": j.get("state"), "secs": j.get("elapsed_s"),
                 "error": scrub(j.get("error") or "", 160) or None} for j in jobs.recent(5)]
    except Exception:
        return []


def issue_url(message: str) -> str:
    """A public GitHub issue instead (opened in the browser for the user to read and post)."""
    from urllib.parse import urlencode
    body = (f"{str(message or '').strip()}\n\n---\nTripShots {__version__} · {sys.platform} "
            f"{context()['osv']} · {platform.machine()}")
    return f"{ISSUES}?{urlencode({'title': (str(message or '').strip().splitlines() or ['Problem'])[0][:80], 'body': body})}"


def send_report(message: str, email: str = "", diagnostics: bool = True) -> dict:
    """Sent because the user pressed Send: needs no usage consent, but honours DO_NOT_TRACK and a missing collector."""
    if not str(message or "").strip():
        return {"ok": False, "error": "write what went wrong first"}
    why = blocked()
    if why:
        return {"ok": False, "error": why, "issue_url": issue_url(message)}
    payload = report_payload(message, email, diagnostics)
    ok, err = _post("/v1/report", payload)
    if ok:
        _append(SENT, {"sent": int(time.time()), "report": payload}, MAX_SENT)
    return {"ok": ok, "error": err, "issue_url": None if ok else issue_url(message)}


# ------------------------------------------------------------------ sending
def _post(path: str, payload: dict, timeout: float = 4.0) -> tuple[bool, str | None]:
    data = json.dumps(payload).encode()
    req = request.Request(endpoint() + path, data=data, method="POST",
                          headers={"Content-Type": "application/json", "User-Agent": f"tripshots/{__version__}"})
    try:
        with request.urlopen(req, timeout=timeout) as r:
            return 200 <= r.status < 300, None
    except Exception as e:  # offline, collector down: try again later
        return False, f"{type(e).__name__}"


def flush(force: bool = False, timeout: float = 4.0) -> dict:
    """Send what is waiting, in batches; keep it when the collector can't be reached."""
    if not enabled():
        return {"sent": 0, "why": blocked() or "not allowed"}
    pick_up_pending()
    with _lock:
        st = _state()
        if not force and time.time() - (st.get("last_try") or 0) < 60:
            return {"sent": 0, "why": "just tried"}
        st["last_try"] = int(time.time())
        _save(st)
        items = _read(QUEUE)
        if not items:
            return {"sent": 0}
        sent = 0
        while items:
            batch, rest = items[:BATCH], items[BATCH:]
            ok, err = _post("/v1/events", {"events": batch}, timeout)
            if not ok:
                _write(QUEUE, items)
                return {"sent": sent, "error": err}
            _append(SENT, {"sent": int(time.time()), "events": batch}, MAX_SENT)
            sent += len(batch)
            items = rest
        _write(QUEUE, [])
        st = _state()
        st["last_sent"] = int(time.time())
        _save(st)
        return {"sent": sent}


def flush_if_due() -> None:
    """At the end of a command-line run: only now and then, never holding the command up for long."""
    if enabled() and (time.time() - (_state().get("last_sent") or 0) > FLUSH_EVERY or _count(QUEUE) > 300):
        flush(timeout=2.0)


def start_background(every: float = 900) -> None:
    """The app's server sends what is waiting every 15 minutes (and shortly after it starts)."""
    def loop():
        time.sleep(20)
        while True:
            try:
                flush(force=True)
            except Exception:
                pass
            time.sleep(every)
    threading.Thread(target=loop, daemon=True, name="telemetry").start()


def sent_log(n: int = 50) -> list[dict]:
    return _read(SENT)[-n:][::-1] if n > 0 else []


# ------------------------------------------------------------------ small files
def _read(p: Path) -> list[dict]:
    try:
        lines = p.read_text().splitlines()
    except OSError:
        return []
    out = []
    for ln in lines:
        try:
            out.append(json.loads(ln))
        except ValueError:
            pass
    return out


def _write(p: Path, items: list[dict]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(x) + "\n" for x in items))
    tmp.replace(p)


def _append(p: Path, item: dict, cap: int) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a") as f:
        f.write(json.dumps(item) + "\n")
    if p.stat().st_size > cap * 600:   # trim now and then, keeping the newest
        items = _read(p)
        if len(items) > cap:
            _write(p, items[-cap:])


def _count(p: Path) -> int:
    try:
        with open(p) as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


# ------------------------------------------------------------------ command line
def cli(action: str) -> dict:
    if action == "on":
        return set_consent(True)
    if action == "off":
        return set_consent(False)
    if action == "reset":
        return reset_id()
    if action == "log":
        return {"sent": sent_log(20), "waiting": _read(QUEUE)[-20:], "errors": recent_errors(10)}
    if action == "send":
        return flush(force=True)
    return status()
