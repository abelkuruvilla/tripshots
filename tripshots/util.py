"""Small shared helpers: logging, subprocess, ffprobe, json, hashing."""
from __future__ import annotations

import functools
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from fractions import Fraction
from pathlib import Path
from typing import Any

VERBOSE = False


def log(msg: str) -> None:
    print(f"[tripshots] {msg}", file=sys.stderr, flush=True)


def debug(msg: str) -> None:
    if VERBOSE:
        print(f"[tripshots:debug] {msg}", file=sys.stderr, flush=True)


class ReelError(RuntimeError):
    pass


def is_mac() -> bool:
    return platform.system() == "Darwin"


def which(name: str) -> str | None:
    return shutil.which(name)


def run(cmd: list[str], *, cwd: str | Path | None = None, timeout: float | None = None,
        check: bool = True, capture: bool = True, env: dict | None = None) -> subprocess.CompletedProcess:
    debug("$ " + " ".join(str(c) for c in cmd))
    proc = subprocess.run([str(c) for c in cmd], cwd=cwd, timeout=timeout, env=env,
                          stdout=subprocess.PIPE if capture else None,
                          stderr=subprocess.PIPE if capture else None, text=True)
    if check and proc.returncode != 0:
        tail = (proc.stderr or "")[-2500:]
        raise ReelError(f"Command failed ({proc.returncode}): {' '.join(str(c) for c in cmd[:6])} ...\n{tail}")
    return proc


def ffmpeg_base() -> list[str]:
    return ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]


def hwaccel_args() -> list[str]:
    # VideoToolbox decode on Macs makes 4K HEVC analysis much faster.
    if is_mac() and os.environ.get("TRIPSHOTS_HWACCEL", "1") != "0":
        return ["-hwaccel", "videotoolbox"]
    return []


@functools.lru_cache(maxsize=None)
def has_filter(name: str) -> bool:
    try:
        out = run(["ffmpeg", "-hide_banner", "-filters"], check=False).stdout
    except FileNotFoundError:
        return False
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == name:
            return True
    return False


def ffprobe(path: str | Path) -> dict:
    proc = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format",
                "-show_streams", str(path)], check=False)
    if proc.returncode != 0:
        raise ReelError(f"ffprobe could not read {path}: {proc.stderr.strip()[:300]}")
    return json.loads(proc.stdout or "{}")


def parse_rate(s: str | None) -> float:
    if not s or s in ("0/0", "N/A"):
        return 0.0
    try:
        return float(Fraction(s))
    except (ValueError, ZeroDivisionError):
        return 0.0


def read_json(path: str | Path, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return default


def write_json(path: str | Path, data: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str))
    tmp.replace(p)


def file_sig(path: str | Path) -> str:
    """Cheap identity for a file: path + size + mtime."""
    p = Path(path)
    st = p.stat()
    return hashlib.sha1(f"{p.resolve()}|{st.st_size}|{int(st.st_mtime)}".encode()).hexdigest()[:16]


def short_hash(text: str, n: int = 10) -> str:
    return hashlib.sha1(text.encode()).hexdigest()[:n]


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out
