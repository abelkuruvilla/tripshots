"""Permanent per-file memory, shared by every run (~/.tripshots/library).

Everything expensive is stored once per *file content*, not per run or folder:
  - media metadata (ffprobe / EXIF, GPS, HDR)
  - local shot analysis (scene cuts, sharpness, shake, thumbnails)
  - the AI's verdict on each shot (score, tags, crop position, notes)

Files are identified by size + a hash of their first and last 256 KB, so a clip is
recognised even if the SSD mounts under another name, the folder is renamed, or the
same file sits in two places. A path index (path+size+mtime -> content key) means
repeat runs only stat() files and never re-read them.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path

from .config import HOME

LIB_DIR = HOME / "library"
DB_PATH = LIB_DIR / "library.db"
THUMBS = LIB_DIR / "thumbs"
STILLS = LIB_DIR / "stills"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS paths  (sig TEXT PRIMARY KEY, key TEXT NOT NULL, path TEXT, seen REAL);
CREATE TABLE IF NOT EXISTS media  (key TEXT PRIMARY KEY, info TEXT NOT NULL, updated REAL);
CREATE TABLE IF NOT EXISTS shots  (key TEXT NOT NULL, version INTEGER NOT NULL, data TEXT NOT NULL,
                                   updated REAL, PRIMARY KEY (key, version));
CREATE TABLE IF NOT EXISTS scores (shot_key TEXT PRIMARY KEY, backend TEXT, data TEXT NOT NULL, updated REAL);
CREATE INDEX IF NOT EXISTS scores_backend ON scores(backend);
CREATE TABLE IF NOT EXISTS analysis (key TEXT NOT NULL, version INTEGER NOT NULL, data TEXT NOT NULL,
                                     updated REAL, PRIMARY KEY (key, version));
"""

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        LIB_DIR.mkdir(parents=True, exist_ok=True)
        THUMBS.mkdir(exist_ok=True)
        STILLS.mkdir(exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.executescript(_SCHEMA)
    return _conn


def _q(sql: str, args=()):
    with _lock:
        return db().execute(sql, args).fetchall()


def _w(sql: str, args=()):
    with _lock:
        c = db()
        c.execute(sql, args)
        c.commit()


def _wmany(sql: str, rows):
    with _lock:
        c = db()
        c.executemany(sql, rows)
        c.commit()


# ------------------------------------------------------------------ identity
def _path_sig(p: Path) -> str:
    st = p.stat()
    return hashlib.sha1(f"{p.resolve()}|{st.st_size}|{st.st_mtime_ns}".encode()).hexdigest()[:20]


def _content_key(p: Path) -> str:
    size = p.stat().st_size
    h = hashlib.sha1(str(size).encode())
    with open(p, "rb") as f:
        h.update(f.read(262144))
        if size > 524288:
            f.seek(-262144, 2)
            h.update(f.read(262144))
    return h.hexdigest()[:20]


def content_key(p: Path) -> str:
    """Stable id for a file's content; cached by path+size+mtime so it's computed once."""
    sig = _path_sig(p)
    row = _q("SELECT key FROM paths WHERE sig=?", (sig,))
    if row:
        return row[0][0]
    key = _content_key(p)
    _w("INSERT OR REPLACE INTO paths(sig, key, path, seen) VALUES (?,?,?,?)", (sig, key, str(p.resolve()), time.time()))
    return key


# --------------------------------------------------------------------- media
def get_media(key: str) -> dict | None:
    row = _q("SELECT info FROM media WHERE key=?", (key,))
    return json.loads(row[0][0]) if row else None


def put_media(key: str, info: dict) -> None:
    _w("INSERT OR REPLACE INTO media(key, info, updated) VALUES (?,?,?)", (key, json.dumps(info, default=str), time.time()))


# --------------------------------------------------------------------- shots
def get_shots(key: str, version: int) -> list | None:
    row = _q("SELECT data FROM shots WHERE key=? AND version=?", (key, version))
    return json.loads(row[0][0]) if row else None


def put_shots(key: str, version: int, shots: list) -> None:
    _w("INSERT OR REPLACE INTO shots(key, version, data, updated) VALUES (?,?,?,?)",
       (key, version, json.dumps(shots, default=str), time.time()))


# ------------------------------------------------------------------ analysis
def get_analysis(key: str, version: int) -> dict | None:
    """Per-file analyzer results (camera, technical metrics per shot; analysis.py)."""
    rows = _q("SELECT data FROM analysis WHERE key=? AND version=?", (key, version))
    return json.loads(rows[0][0]) if rows else None


def put_analysis(key: str, version: int, data: dict) -> None:
    _w("INSERT OR REPLACE INTO analysis(key, version, data, updated) VALUES (?,?,?,?)",
       (key, version, json.dumps(data, default=str), time.time()))


# -------------------------------------------------------------------- scores
def shot_key(shot: dict) -> str:
    return f"{shot['sig']}@{float(shot['t0']):.3f}"


def get_scores(keys: list[str], backend: str | None = None) -> dict[str, dict]:
    """Stored AI verdicts for these shots. backend=None accepts a verdict from any backend."""
    out: dict[str, dict] = {}
    for i in range(0, len(keys), 500):
        chunk = keys[i:i + 500]
        marks = ",".join("?" * len(chunk))
        if backend:
            rows = _q(f"SELECT shot_key, backend, data FROM scores WHERE backend=? AND shot_key IN ({marks})",
                      (backend, *chunk))
        else:
            rows = _q(f"SELECT shot_key, backend, data FROM scores WHERE shot_key IN ({marks})", tuple(chunk))
        for k, b, d in rows:
            out[k] = {**json.loads(d), "source": b}
    return out


def put_scores(scores: dict[str, dict], backend: str) -> None:
    now = time.time()
    _wmany("INSERT OR REPLACE INTO scores(shot_key, backend, data, updated) VALUES (?,?,?,?)",
           [(k, backend, json.dumps(v, default=str), now) for k, v in scores.items()])


def forget_scores(keys: list[str] | None = None) -> int:
    if keys is None:
        n = _q("SELECT COUNT(*) FROM scores")[0][0]
        _w("DELETE FROM scores")
        return n
    n = 0
    for i in range(0, len(keys), 500):
        chunk = keys[i:i + 500]
        marks = ",".join("?" * len(chunk))
        n += _q(f"SELECT COUNT(*) FROM scores WHERE shot_key IN ({marks})", tuple(chunk))[0][0]
        _w(f"DELETE FROM scores WHERE shot_key IN ({marks})", tuple(chunk))
    return n


# --------------------------------------------------------------------- stats
def stats() -> dict:
    files = _q("SELECT COUNT(*) FROM media")[0][0]
    shots = sum(len(json.loads(d)) for (d,) in _q("SELECT data FROM shots"))
    by_backend = dict(_q("SELECT backend, COUNT(*) FROM scores GROUP BY backend"))
    size = sum(f.stat().st_size for f in LIB_DIR.rglob("*") if f.is_file())
    return {"files": files, "shots": shots, "ai_scored_shots": by_backend, "disk_mb": round(size / 1e6, 1),
            "location": str(LIB_DIR)}
