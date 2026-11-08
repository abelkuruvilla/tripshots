"""Your Instagram login, borrowed from a browser you're logged in with, for downloading reels.

yt-dlp reads browser cookies itself, but when it can't it says little ("could not find brave cookies database"),
and some browsers it doesn't know (Arc). This module:
  * checks each browser cheaply (is it installed, can its cookie store be read, which profiles) without
    decrypting anything, so a failure says exactly why: not installed, no cookie store, or macOS privacy
    blocking the terminal (Safari needs Full Disk Access);
  * with "auto", tries every readable browser and uses the first one that has an Instagram session;
  * hands yt-dlp only the instagram.com cookies, in a private temporary cookies.txt that is deleted at exit.
Chromium browsers on macOS keep their cookies encrypted with a key in the Keychain: macOS asks once
("python wants to use … Safe Storage"); choose Always Allow.
"""
from __future__ import annotations

import atexit
import os
import sys
import tempfile
from pathlib import Path

from .util import ReelError, log

ORDER = ["chrome", "safari", "brave", "arc", "firefox", "edge", "vivaldi", "opera", "chromium"]
NAMES = {"chrome": "Chrome", "safari": "Safari", "brave": "Brave", "arc": "Arc", "firefox": "Firefox",
         "edge": "Edge", "vivaldi": "Vivaldi", "opera": "Opera", "chromium": "Chromium"}
# Chromium browsers yt-dlp doesn't know: data folder (macOS) and Keychain name
EXTRA_CHROMIUM = {"arc": ("Arc/User Data", "Arc")}
_cache: dict[str, tuple[str, str]] = {}   # spec -> (cookie file, browser label)


def _home() -> Path:
    return Path.home()


def terminal_app() -> str:
    """The app TripShots runs in, as macOS names it in Privacy & Security."""
    tp = os.environ.get("TERM_PROGRAM", "")
    return {"Apple_Terminal": "Terminal", "iTerm.app": "iTerm", "vscode": "Visual Studio Code",
            "WarpTerminal": "Warp", "ghostty": "Ghostty", "WezTerm": "WezTerm", "tmux": "your terminal app"
            }.get(tp, tp or "your terminal app")


def _chromium_dir(browser: str) -> Path | None:
    h = _home()
    if sys.platform == "darwin":
        a = h / "Library/Application Support"
        d = {"chrome": "Google/Chrome", "brave": "BraveSoftware/Brave-Browser", "edge": "Microsoft Edge",
             "vivaldi": "Vivaldi", "opera": "com.operasoftware.Opera", "chromium": "Chromium",
             "arc": EXTRA_CHROMIUM["arc"][0]}.get(browser)
        return a / d if d else None
    if sys.platform.startswith("win"):
        la = Path(os.environ.get("LOCALAPPDATA", h / "AppData/Local"))
        ra = Path(os.environ.get("APPDATA", h / "AppData/Roaming"))
        d = {"chrome": la / "Google/Chrome/User Data", "brave": la / "BraveSoftware/Brave-Browser/User Data",
             "edge": la / "Microsoft/Edge/User Data", "vivaldi": la / "Vivaldi/User Data",
             "opera": ra / "Opera Software/Opera Stable", "chromium": la / "Chromium/User Data"}
        return d.get(browser)
    c = Path(os.environ.get("XDG_CONFIG_HOME", h / ".config"))
    d = {"chrome": "google-chrome", "brave": "BraveSoftware/Brave-Browser", "edge": "microsoft-edge",
         "vivaldi": "vivaldi", "opera": "opera", "chromium": "chromium"}.get(browser)
    return c / d if d else None


def _walk(root: Path, name: str, depth: int = 4) -> tuple[list[Path], bool]:
    """Files called `name` under root (a few levels deep), and whether a folder couldn't be read."""
    found, blocked = [], False

    def go(d: Path, lvl: int):
        nonlocal blocked
        try:
            entries = list(os.scandir(d))
        except PermissionError:
            blocked = True
            return
        except OSError:
            return
        for e in entries:
            try:
                if e.is_file() and e.name == name:
                    found.append(Path(e.path))
                elif e.is_dir(follow_symlinks=False) and lvl < depth and e.name not in ("Cache", "Code Cache",
                                                                                          "Service Worker"):
                    go(Path(e.path), lvl + 1)
            except OSError:
                continue
    go(root, 0)
    return found, blocked


def check(browser: str) -> dict:
    """Cheap look at a browser's cookie store (nothing decrypted, no Keychain prompt).
    status: ok | not_installed | blocked | no_store | unsupported"""
    b = browser.lower()
    out = {"browser": b, "name": NAMES.get(b, b), "status": "ok", "detail": "", "store": None, "profiles": []}
    if b == "safari":
        if sys.platform != "darwin":
            return {**out, "status": "unsupported", "detail": "Safari is only on macOS"}
        cands = [_home() / "Library/Containers/com.apple.Safari/Data/Library/Cookies/Cookies.binarycookies",
                 _home() / "Library/Cookies/Cookies.binarycookies"]
        for p in cands:
            try:
                with open(p, "rb") as fh:
                    fh.read(4)
                return {**out, "store": str(p)}
            except FileNotFoundError:
                continue
            except PermissionError:
                return {**out, "status": "blocked", "store": str(p),
                        "detail": f"macOS doesn't let {terminal_app()} read Safari's cookies. Give it Full Disk Access: "
                                  "System Settings → Privacy & Security → Full Disk Access → turn on "
                                  f"{terminal_app()} (or add it with +), then quit and reopen it"}
        container = _home() / "Library/Containers/com.apple.Safari"
        if container.exists():
            return {**out, "status": "blocked",
                    "detail": f"Safari's cookie file can't be seen from {terminal_app()}. Give it Full Disk Access "
                              "(System Settings → Privacy & Security → Full Disk Access), then quit and reopen it"}
        return {**out, "status": "no_store", "detail": "no Safari cookie file found"}
    if b == "firefox":
        roots = {"darwin": [_home() / "Library/Application Support/Firefox/Profiles"]}.get(
            sys.platform, [_home() / ".mozilla/firefox", _home() / ".config/mozilla/firefox",
                           _home() / "snap/firefox/common/.mozilla/firefox"])
        if sys.platform.startswith("win"):
            roots = [Path(os.environ.get("APPDATA", "")) / "Mozilla/Firefox/Profiles"]
        roots = [r for r in roots if r.exists()]
        if not roots:
            return {**out, "status": "not_installed", "detail": "no Firefox profile folder"}
        files, blocked = [], False
        for r in roots:
            f, bl = _walk(r, "cookies.sqlite", 2)
            files += f
            blocked |= bl
        if not files:
            return {**out, "status": "blocked" if blocked else "no_store",
                    "detail": "Firefox's profile folder couldn't be read" if blocked else "no Firefox cookie database"}
        return {**out, "store": str(max(files, key=lambda p: p.stat().st_mtime)),
                "profiles": [p.parent.name for p in files]}
    root = _chromium_dir(b)
    if root is None:
        return {**out, "status": "unsupported", "detail": f"{out['name']} isn't supported on this system"}
    if not root.exists():
        sib = [p.name for p in root.parent.glob(root.name + "*") if p.is_dir()] if root.parent.exists() else []
        detail = f"no {out['name']} data at {root}"
        if sib:
            detail += f" (found {', '.join(sib)}: Beta/Nightly builds aren't supported; use the main build or a cookies.txt)"
        return {**out, "status": "not_installed", "detail": detail}
    files, blocked = _walk(root, "Cookies")
    if not files:
        if blocked:
            return {**out, "status": "blocked",
                    "detail": f"macOS stopped {terminal_app()} from reading {root}. Give it Full Disk Access (System "
                              "Settings → Privacy & Security → Full Disk Access), then quit and reopen it"}
        profiles = sorted(p.name for p in root.iterdir() if (p / "Preferences").exists()) if root.exists() else []
        return {**out, "status": "no_store", "profiles": profiles,
                "detail": f"{out['name']} is installed but has no cookie database in {root}"
                          + (f" (profiles: {', '.join(profiles)})" if profiles else " (no profiles: has it been opened?)")}
    newest = max(files, key=lambda p: p.stat().st_mtime)
    rel = newest.relative_to(root).parts
    return {**out, "store": str(newest), "profiles": sorted({p.relative_to(root).parts[0] for p in files}),
            "profile": rel[0] if len(rel) > 1 else None}


def _register_extra() -> None:
    """Teach yt-dlp the Chromium browsers it doesn't know (Arc), with their data folder and Keychain name."""
    import yt_dlp.cookies as yc
    if getattr(yc, "_tripshots_extra", False):
        return
    orig = yc._get_chromium_based_browser_settings

    def settings(name):
        if name in EXTRA_CHROMIUM:
            folder, keyring = EXTRA_CHROMIUM[name]
            return {"browser_dir": str(_home() / "Library/Application Support" / folder), "keyring_name": keyring,
                    "supports_profiles": True}
        return orig(name)
    yc._get_chromium_based_browser_settings = settings
    yc.CHROMIUM_BASED_BROWSERS = set(yc.CHROMIUM_BASED_BROWSERS) | set(EXTRA_CHROMIUM)
    yc.SUPPORTED_BROWSERS = set(yc.SUPPORTED_BROWSERS) | set(EXTRA_CHROMIUM)
    yc._tripshots_extra = True


class _Log:
    def debug(self, *a, **k):
        pass

    info = debug

    def warning(self, msg, *a, **k):
        if "decrypt" in str(msg).lower() or "keyring" in str(msg).lower():
            log(f"cookies: {msg}")

    def error(self, msg, *a, **k):
        log(f"cookies: {msg}")


def _load(browser: str, profile: str | None):
    import yt_dlp.cookies as yc
    _register_extra()
    return yc.extract_cookies_from_browser(browser, profile, _Log())


def _instagram(jar) -> list:
    return [c for c in jar if c.domain.lstrip(".").endswith("instagram.com")]


def _session(cookies: list) -> bool:
    return any(c.name == "sessionid" and c.value for c in cookies)


def _write(cookies: list) -> str:
    from http.cookiejar import MozillaCookieJar
    fd, path = tempfile.mkstemp(prefix="tripshots-ig-", suffix=".txt")
    os.close(fd)
    os.chmod(path, 0o600)
    jar = MozillaCookieJar(path)
    for c in cookies:
        jar.set_cookie(c)
    jar.save(ignore_discard=True, ignore_expires=True)
    atexit.register(lambda: Path(path).unlink(missing_ok=True))
    return path


def _try(browser: str, profile: str | None) -> tuple[str | None, str]:
    """(cookie file, '') when the browser has an Instagram session, else (None, why not)."""
    st = check(browser)
    if st["status"] != "ok":
        return None, st["detail"] or "unknown problem"
    try:
        jar = _load(browser, profile)
    except PermissionError:
        return None, (f"macOS blocked reading {st['name']}'s cookies. Give {terminal_app()} Full Disk Access (System "
                      "Settings → Privacy & Security → Full Disk Access), then quit and reopen it")
    except FileNotFoundError as e:
        return None, str(e)
    except Exception as e:  # Keychain refused, database locked, unknown format…
        low = str(e).lower()
        if "keychain" in low or "safe storage" in low or "password" in low:
            return None, (f"the Keychain didn't give the key to {st['name']}'s cookies; run again and choose "
                          "Always Allow when macOS asks")
        return None, f"couldn't read {st['name']}'s cookies ({str(e)[:120]})"
    ig = _instagram(jar)
    if not _session(ig):
        where = f" (profile {profile})" if profile else ""
        return None, (f"{st['name']}{where} isn't logged in to Instagram. Reels play there without a login, but "
                      f"downloading needs one: log in at instagram.com in {st['name']}, then retry")
    return _write(ig), ""


def cookie_file(spec: str) -> tuple[str, str]:
    """Resolve '--cookies-from-browser' (a browser, 'browser:Profile 1' or 'auto') to a private cookies.txt
    holding the Instagram login. Returns (path, label). Raises ReelError saying exactly what to fix."""
    spec = spec.strip()
    if spec in _cache:
        return _cache[spec]
    name, _, profile = spec.partition(":")
    name = name.lower()
    if name == "auto":
        notes = []
        for b in ORDER:
            st = check(b)
            if st["status"] in ("not_installed", "unsupported"):
                continue
            path, why = _try(b, None)
            if path:
                log(f"using the Instagram login from {NAMES[b]}")
                _cache[spec] = (path, NAMES[b])
                return _cache[spec]
            notes.append(f"  {NAMES[b]}: {why}")
        raise ReelError("no browser with an Instagram login could be used:\n" + ("\n".join(notes) or
                        "  no supported browser found") + "\n" + _alternative())
    if name not in NAMES:
        raise ReelError(f"unknown browser '{name}': use one of {', '.join(ORDER)} or auto")
    path, why = _try(name, profile or None)
    if path:
        _cache[spec] = (path, NAMES[name])
        return _cache[spec]
    others = []
    for b in ORDER:
        if b != name:
            st = check(b)
            if st["status"] == "ok":
                others.append(NAMES[b])
    tip = (f"\nOther browsers TripShots can read: {', '.join(others)}. `--cookies-from-browser auto` tries each "
           "and uses the one that's logged in.") if others else ""
    raise ReelError(f"can't use the Instagram login from {NAMES[name]}: {why}{tip}\n{_alternative()}")


def _alternative() -> str:
    return ("Or export a cookies.txt while on instagram.com (a browser extension such as \"Get cookies.txt "
            "LOCALLY\") and pass --cookies FILE (or set it in the app's Settings).")


def report() -> list[dict]:
    """Every browser's status, for `tripshots cookies` (no decryption unless check_login)."""
    return [check(b) for b in ORDER]


def login_status(browser: str) -> str:
    """'ok' or why not (decrypts: may trigger the Keychain prompt)."""
    name, _, profile = browser.partition(":")
    if name.lower() not in NAMES:
        return f"unknown browser '{name}'"
    path, why = _try(name.lower(), profile or None)
    if path:
        Path(path).unlink(missing_ok=True)
        return "ok"
    return why
