"""Style inboxes: share a reel on your phone, and the style it was shared to learns it.

The inbox is a folder (iCloud Drive/TripShots by default, so a phone can write to it) with one text file per
style: `westcoast.txt` feeds the style `westcoast`. An iPhone Shortcut in Instagram's share sheet appends the
reel's link to the file; any text works, only Instagram links are read. `sync` finds links a style hasn't
learned yet, downloads each (the same way `learn` does), and re-learns the style once with all of them.
The files are only read, never rewritten (a phone may be writing to them at the same time).
"""
from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

from .config import BUILTIN_STYLES, HOME, USER_STYLES
from .util import ReelError, log, read_json, write_json

STATE = HOME / "inbox.json"
LOCK = HOME / "inbox.lock"
ICLOUD = Path.home() / "Library" / "Mobile Documents" / "com~apple~CloudDocs"
LINK = re.compile(r"https?://(?:www\.)?instagram\.com/(?:[A-Za-z0-9_.]+/)?(?:reels?|p|tv)/([A-Za-z0-9_-]+)[^\s]*",
                  re.I)
GIVE_UP = 3          # a reel that fails to download this many syncs in a row is skipped for good
LABEL = "dev.tripshots.inbox"
README = """TripShots style inbox

Each .txt file here feeds the style with the same name: links in westcoast.txt are learned by `westcoast`.
Add a link by sharing a reel to the "Add to TripShots" shortcut, or paste it on a new line.
A new file makes a new style. The Mac reads these files and never changes them.
"""


def folder() -> Path:
    env = os.environ.get("TRIPSHOTS_INBOX")
    if env:
        return Path(env).expanduser()
    return ICLOUD / "TripShots" if ICLOUD.is_dir() else HOME / "inbox"


def style_name(stem: str) -> str | None:
    """'westcoast' -> 'westcoast'; 'Calm sunsets' -> 'calm-sunsets'; 'TripShots beach' -> 'beach'."""
    stem = re.sub(r"^\s*trip\s*shots\b[\s:_-]*", "", stem, flags=re.I)
    name = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")
    return name or None


def code_of(url: str) -> str | None:
    m = LINK.search(url or "")
    return m.group(1) if m else None


def reel_url(code: str) -> str:
    return f"https://www.instagram.com/reel/{code}/"


def links(text: str) -> list[str]:
    """Instagram links in the order they were added, each reel once, tracking parameters dropped."""
    return list(dict.fromkeys(reel_url(m.group(1)) for m in LINK.finditer(text or "")))


def inboxes(root: Path | None = None) -> dict[str, list[str]]:
    """style -> its links, from every .txt in the inbox (two files may feed one style)."""
    root = root or folder()
    out: dict[str, list[str]] = {}
    for p in sorted(root.glob("*.txt")) if root.is_dir() else []:
        name = style_name(p.stem)
        if not name or p.name.lower() == "readme.txt":
            continue
        try:
            text = p.read_text(errors="replace")
        except OSError as e:   # iCloud hasn't downloaded it yet
            log(f"can't read {p.name} yet ({e})")
            continue
        out.setdefault(name, [])
        out[name] = list(dict.fromkeys(out[name] + links(text)))
    return out


def setup(root: Path | None = None) -> Path:
    root = root or folder()
    root.mkdir(parents=True, exist_ok=True)
    (root / "README.txt").write_text(README)
    return root


# --- state --------------------------------------------------------------------------------------------------

def load_state() -> dict:
    st = read_json(STATE, {}) or {}
    st.setdefault("failed", {})    # reel code -> {n, why}
    st.setdefault("added", {})     # style -> [reel links added from the inbox]
    return st


def save_state(st: dict) -> None:
    write_json(STATE, st)


def _style_file(name: str) -> Path | None:
    for d in (USER_STYLES, BUILTIN_STYLES):
        p = d / f"{name}.yaml"
        if p.exists():
            return p
    return None


def learned_from(name: str) -> list[str] | None:
    """The style's reference reels; [] for a style that doesn't exist yet; None if it wasn't learned from reels."""
    import yaml
    p = _style_file(name)
    if not p:
        return []
    refs = (yaml.safe_load(p.read_text()) or {}).get("learned_from")
    return list(refs) if refs else None


# --- sync ---------------------------------------------------------------------------------------------------

def _lock() -> bool:
    try:
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        if time.time() - LOCK.stat().st_mtime < 3 * 3600:
            return False
        LOCK.unlink(missing_ok=True)   # left behind by a run that died
        return _lock()
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    return True


def sync(cookies_browser: str | None = None, cookies_file: str | None = None, backend: str | None = None,
         dry_run: bool = False, root: Path | None = None, learn_fn=None, fetch_fn=None) -> dict:
    """Re-learn each style whose inbox has reels it hasn't learned. Returns a report."""
    root = root or folder()
    report: dict = {"folder": str(root), "styles": {}}
    if not root.is_dir():
        report["hint"] = f"no inbox yet: run `tripshots inbox setup` (makes {root})"
        return report
    HOME.mkdir(parents=True, exist_ok=True)
    if not dry_run and not _lock():
        raise ReelError("another `tripshots inbox sync` is running")
    try:
        st = load_state()
        for style, urls in inboxes(root).items():
            r = report["styles"][style] = {"new": [], "skipped": []}
            old = learned_from(style)
            if old is None:
                if urls:
                        r["error"] = (f"'{style}' is a hand-made style, not one learned from reels: rename "
                                  f"{style}.txt (e.g. {style}-learned.txt) so it doesn't replace it")
                continue
            have = {code_of(u) for u in old}
            for url in urls:
                code = code_of(url)
                if code in have:
                    continue
                (r["skipped"] if st["failed"].get(code, {}).get("n", 0) >= GIVE_UP else r["new"]).append(url)
            if dry_run or not r["new"]:
                continue
            # download first, one by one: a deleted or private reel must not stop the others from being learned
            from . import fetch
            work = HOME / "learn" / style / "downloads"
            ok = []
            for url in r["new"]:
                try:
                    (fetch_fn or fetch.fetch_video)(url, work, cookies_browser, cookies_file)
                    ok.append(url)
                    st["failed"].pop(code_of(url), None)
                except ReelError as e:
                    f = st["failed"].setdefault(code_of(url), {"n": 0})
                    f["n"] += 1
                    f["why"] = str(e)[:200]
                    r["skipped"].append(url)
            r["new"] = ok
            save_state(st)
            if not ok:
                continue
            log(f"'{style}' learns {len(ok)} new reel(s) from the inbox")
            try:
                if learn_fn is None:
                    from .learn import learn as learn_fn
                learn_fn(list(dict.fromkeys(old + ok)), style, backend, cookies_browser, cookies_file)
                st["added"].setdefault(style, []).extend(ok)
            except Exception as e:   # not in learned_from yet, so the next sync tries again
                r["error"] = str(e)[:300]
                r["new"] = []
            save_state(st)
        if not dry_run:
            st["last_sync"] = time.strftime("%Y-%m-%d %H:%M")
            save_state(st)
        return report
    finally:
        if not dry_run:
            LOCK.unlink(missing_ok=True)


def summary(report: dict) -> str:
    out = []
    for style, r in report.get("styles", {}).items():
        if r.get("error"):
            out.append(f"{style}: {r['error'][:120]}")
        elif r["new"]:
            out.append(f"{style} learned {len(r['new'])} new reel(s)")
        if r.get("skipped"):
            out.append(f"{style}: {len(r['skipped'])} reel(s) couldn't be downloaded")
    return "; ".join(out)


def notify(text: str) -> None:
    """A macOS notification (the background sync has no window)."""
    if sys.platform == "darwin" and text:
        import subprocess
        msg = text.replace("\\", "").replace('"', "'")[:200]
        subprocess.run(["osascript", "-e", f'display notification "{msg}" with title "TripShots"'],
                       capture_output=True, timeout=10)


# --- background (macOS launchd) -------------------------------------------------------------------------------

def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def plist(root: Path, hours: float, cookies_browser: str | None, cookies_file: str | None) -> str:
    """Runs when a file in the inbox changes (a phone's share lands in seconds once iCloud syncs) and every
    `hours` as a fallback."""
    from xml.sax.saxutils import escape
    args = [sys.executable, "-m", "tripshots", "inbox", "sync", "--notify"]
    if cookies_file:
        args += ["--cookies", str(Path(cookies_file).expanduser().resolve())]
    elif cookies_browser:
        args += ["--cookies-from-browser", cookies_browser]
    logf = HOME / "inbox.log"
    arg_xml = "".join(f"\n      <string>{escape(a)}</string>" for a in args)
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "TRIPSHOTS_INBOX": str(root)}
    env_xml = "".join(f"\n      <key>{k}</key><string>{escape(v)}</string>" for k, v in env.items())
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key><string>{LABEL}</string>
    <key>ProgramArguments</key>
    <array>{arg_xml}
    </array>
    <key>WatchPaths</key>
    <array>
      <string>{escape(str(root))}</string>
    </array>
    <key>StartInterval</key><integer>{int(hours * 3600)}</integer>
    <key>ThrottleInterval</key><integer>60</integer>
    <key>RunAtLoad</key><true/>
    <key>StandardOutPath</key><string>{escape(str(logf))}</string>
    <key>StandardErrorPath</key><string>{escape(str(logf))}</string>
    <key>EnvironmentVariables</key>
    <dict>{env_xml}
    </dict>
  </dict>
</plist>
"""


def watch(on: bool, hours: float = 6, cookies_browser: str | None = None, cookies_file: str | None = None) -> str:
    """Sync in the background whenever the inbox changes (macOS)."""
    if sys.platform != "darwin":
        raise ReelError("the background watch uses macOS launchd; elsewhere run `tripshots inbox sync` from cron "
                        "or a scheduled task")
    import subprocess
    p = plist_path()
    if p.exists():
        subprocess.run(["launchctl", "unload", str(p)], capture_output=True)
    if not on:
        p.unlink(missing_ok=True)
        return "stopped: the inbox is no longer watched"
    if not 1 <= hours <= 48:
        raise ReelError("--every takes 1 to 48 hours")
    root = setup()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(plist(root, hours, cookies_browser, cookies_file))
    out = subprocess.run(["launchctl", "load", str(p)], capture_output=True, text=True)
    if out.returncode:
        raise ReelError(f"launchctl couldn't start it: {out.stderr.strip()[:200]}")
    return f"watching {root} (and checking every {hours:g} h); log: {HOME / 'inbox.log'}"
