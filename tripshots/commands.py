"""CLI argument lists for the long commands, shared by the MCP server and the desktop app's local API (server.py),
so both start exactly the same `tripshots ...` job for the same request."""
from __future__ import annotations

import os
import re
from pathlib import Path

MAKE_FLAGS = (("music", "-m"), ("style", "-s"), ("duration", "-d"), ("hook", "--hook"), ("location", "--location"),
              ("look", "--look"), ("text_preset", "--text-preset"), ("route_map", "--route-map"),
              ("speed_ramps", "--speed-ramps"), ("speed_up", "--speed-up"), ("drop_speed", "--drop-speed"),
              ("format", "--format"), ("text_motion", "--text-motion"), ("captions", "--captions"),
              ("recipe", "--recipe"), ("orientation", "--orientation"), ("fresh", "--fresh"),
              ("light", "--light"))


def default_out() -> None:
    """The reels folder when none is set: the app's last one, else ~/Movies/Reels (Mac) or ~/reels."""
    if not os.environ.get("TRIPSHOTS_OUT"):
        from .config import HOME
        from .util import is_mac, read_json
        st = read_json(HOME / "tui.json", {}) or {}
        os.environ["TRIPSHOTS_OUT"] = st.get("out_dir") or str(
            (Path.home() / "Movies" / "Reels") if is_mac() else (Path.home() / "reels"))


def reel_out(name: str) -> str:
    """Where a named reel goes: the reels folder, with a file name that is safe on every system."""
    safe = re.sub(r"[^A-Za-z0-9 ._-]+", "-", name).strip(" .-")[:80] or "reel"
    return str(Path(os.environ.get("TRIPSHOTS_OUT") or Path.cwd() / "reels") / f"{safe}.mp4")


def make_args(sources: list[str], *, variants: int = 1, upload_copy: bool = False, no_location: bool = False,
              dry_run: bool = True, name: str | None = None, **opts) -> list[str]:
    """`tripshots make ...` for these options (the keys of MAKE_FLAGS; None or "" = the default)."""
    args = ["make"]
    for key, flag in MAKE_FLAGS:
        v = opts.get(key)
        if v not in (None, ""):
            args += [flag, str(v)]
    if variants and int(variants) > 1:
        args += ["--variants", str(int(variants))]
    if upload_copy:
        args.append("--upload-copy")
    if no_location:
        args.append("--no-location")
    if dry_run:
        args.append("--dry-run")
    if name:
        args += ["-o", reel_out(name)]
    return args + ["--", *sources]  # paths after "--": never read as options


def find_args(place: str | None = None, people: list[str] | None = None, date_from: str | None = None,
              date_to: str | None = None, near_lat: float | None = None, near_lon: float | None = None,
              radius_km: float = 10, kinds: str = "both", any_people: bool = False, whole_days: bool = True,
              text: str | None = None, folders: list[str] | None = None, label: str | None = None,
              camera: str | None = None) -> list[str]:
    args = ["find", "--sheet", "--kind", kinds]
    if place:
        args += ["--place", place]
    if near_lat is not None and near_lon is not None:
        args += ["--near", f"{near_lat},{near_lon}", "--radius", str(radius_km)]
    if people:
        args += ["--people", *people] + (["--any-people"] if any_people else [])
    for flag, v in (("--since", date_from), ("--until", date_to), ("--text", text), ("--name", label),
                    ("--camera", camera)):
        if v:
            args += [flag, v]
    if not whole_days:
        args.append("--only-matching")
    return args + ["--", *(folders or [])]
