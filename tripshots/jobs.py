"""Background jobs: long CLI runs (analyse, plan, render) started by an agent and polled.

Each job is `python -m tripshots <args>` in its own process: stdout (the command's JSON result)
goes to <id>.out, the log to <id>.log. State lives on disk, so a job outlives the MCP server
that started it and any later server can report on it.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

from .config import HOME
from .util import read_json, write_json

JOB_DIR = HOME / "jobs"
_procs: dict[str, subprocess.Popen] = {}


def start(args: list[str], kind: str, label: str = "") -> str:
    JOB_DIR.mkdir(parents=True, exist_ok=True)
    jid = time.strftime("%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
    out, log = JOB_DIR / f"{jid}.out", JOB_DIR / f"{jid}.log"
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    with open(out, "wb") as fo, open(log, "wb") as fl:
        p = subprocess.Popen([sys.executable, "-m", "tripshots", *args], stdout=fo, stderr=fl,
                             stdin=subprocess.DEVNULL, env=env, start_new_session=True)
    _procs[jid] = p
    write_json(JOB_DIR / f"{jid}.json", {"id": jid, "kind": kind, "label": label, "args": args, "pid": p.pid,
                                         "started": time.time()})
    return jid


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:  # a zombie child of this process counts as finished
        done, _ = os.waitpid(pid, os.WNOHANG)
        return done == 0
    except ChildProcessError:
        return True


def _result(out: Path):
    text = out.read_text(errors="ignore").strip() if out.exists() else ""
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        i = text.rfind("\n{")
        try:
            return json.loads(text[i + 1:] if i >= 0 else text[text.find("{"):])
        except Exception:
            return {"output": text[-2000:]}


def log_tail(jid: str, n: int = 14) -> list[str]:
    p = JOB_DIR / f"{jid}.log"
    if not p.exists():
        return []
    lines = [ln.replace("[tripshots] ", "").rstrip() for ln in p.read_text(errors="ignore").splitlines()
             if ln.strip() and "WARN:" not in ln]
    return lines[-n:]


def status(jid: str) -> dict:
    meta = read_json(JOB_DIR / f"{jid}.json")
    if not meta:
        return {"id": jid, "state": "unknown", "error": "no such job"}
    p = _procs.get(jid)
    if p is not None:
        rc = p.poll()
        running = rc is None
    else:
        rc = meta.get("rc")
        running = rc is None and _alive(meta["pid"])
    st = {"id": jid, "kind": meta["kind"], "label": meta.get("label"), "command": "tripshots " + " ".join(meta["args"]),
          "elapsed_s": round((meta.get("ended") or time.time()) - meta["started"]), "log": log_tail(jid)}
    if running:
        st["state"] = "running"
        return st
    if meta.get("rc") is None:
        meta["rc"] = rc if rc is not None else (0 if _result(JOB_DIR / f"{jid}.out") else 1)
        meta["ended"] = time.time()
        write_json(JOB_DIR / f"{jid}.json", meta)
    res = _result(JOB_DIR / f"{jid}.out")
    ok = meta["rc"] == 0 and res is not None
    st.update({"state": "done" if ok else "failed", "result": res})
    if not ok:
        errs = [ln for ln in log_tail(jid, 60) if "error" in ln.lower() or "failed" in ln.lower()]
        st["error"] = errs[-1] if errs else (st["log"][-1] if st["log"] else "failed")
    return st


def wait(jid: str, seconds: float) -> dict:
    end = time.time() + max(0.0, seconds)
    while True:
        st = status(jid)
        if st["state"] != "running" or time.time() >= end:
            return st
        time.sleep(1.0)


def cancel(jid: str) -> dict:
    meta = read_json(JOB_DIR / f"{jid}.json")
    if not meta:
        return {"id": jid, "state": "unknown"}
    try:
        os.killpg(meta["pid"], signal.SIGTERM)
    except OSError:
        pass
    return status(jid)


def recent(n: int = 8) -> list[dict]:
    if not JOB_DIR.exists():
        return []
    metas = sorted(JOB_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:n]
    out = []
    for m in metas:
        st = status(m.stem)
        out.append({k: st.get(k) for k in ("id", "kind", "label", "state", "elapsed_s")})
    return out
