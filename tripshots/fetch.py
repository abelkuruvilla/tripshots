"""Download media from an Instagram reel (or any yt-dlp supported) link.

Uses yt-dlp (https://github.com/yt-dlp/yt-dlp, public domain / Unlicense) as a library.

The audio is meant as a *timing reference*: tripshots cuts your footage to its beat,
and you attach the same sound inside Instagram when posting, so the post uses
Instagram's licensed copy instead of a re-uploaded one.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from .config import HOME
from .util import ReelError, log, read_json, short_hash, which, write_json

MUSIC_DIR = HOME / "music"
URL_RE = re.compile(r"^https?://", re.I)
AUDIO_EXT = (".m4a", ".mp3", ".aac", ".opus", ".ogg", ".wav", ".webm", ".mp4")


def is_url(s: str | None) -> bool:
    return bool(s and URL_RE.match(s.strip()))


def canonical(url: str) -> str:
    """Strip tracking params so the same reel always maps to the same cache entry."""
    url = url.strip()
    m = re.match(r"(https?://(?:www\.)?instagram\.com/(?:reels?|p|tv)/[A-Za-z0-9_-]+)", url, re.I)
    if m:
        return m.group(1).replace("/reels/", "/reel/") + "/"
    return url.split("?")[0] if "instagram.com" in url else url


def _cookie_opts(cookies_browser: str | None, cookies_file: str | None) -> dict:
    cookies_browser = cookies_browser or os.environ.get("TRIPSHOTS_COOKIES_BROWSER")
    cookies_file = cookies_file or os.environ.get("TRIPSHOTS_COOKIES_FILE")
    opts: dict = {}
    if cookies_file:
        p = Path(cookies_file).expanduser()
        if not p.exists():
            raise ReelError(f"cookies file not found: {p}")
        opts["cookiefile"] = str(p)
    elif cookies_browser:
        # e.g. "chrome", "safari", "firefox", "chrome:Profile 1"
        name, _, profile = cookies_browser.partition(":")
        opts["cookiesfrombrowser"] = (name.lower(), profile or None, None, None)
    return opts


def _ydl(extra: dict):
    try:
        import yt_dlp
    except ImportError as e:
        raise ReelError("yt-dlp is not installed: run ./install.sh again (or `pip install yt-dlp`)") from e
    if not which("ffmpeg"):
        raise ReelError("ffmpeg is required to extract audio")

    class _Quiet:
        def debug(self, msg):
            pass

        def info(self, msg):
            pass

        def warning(self, msg):
            if "cookies" in msg.lower() or "login" in msg.lower():
                log(f"yt-dlp: {msg}")

        def error(self, msg):
            pass

    base = {"quiet": True, "no_warnings": False, "noprogress": True, "logger": _Quiet(),
            "noplaylist": True, "retries": 3, "socket_timeout": 30}
    base.update(extra)
    return yt_dlp.YoutubeDL(base)


def _friendly(err: Exception, used_cookies: bool) -> ReelError:
    msg = str(err)
    low = msg.lower()
    if any(k in low for k in ("proxy", "unable to connect", "name resolution", "timed out", "network is unreachable")):
        return ReelError(f"could not reach the site (network problem): {msg.splitlines()[-1][:200]}")
    if any(k in low for k in ("login", "rate-limit", "rate limit", "cookies", "not available", "401", "403", "private")):
        hint = ("Instagram wants a logged-in session. Re-run with --cookies-from-browser chrome "
                "(or safari/firefox; you must be logged in to instagram.com in that browser). "
                "On macOS, Safari needs Full Disk Access for your terminal.") if not used_cookies else \
               ("Still blocked with cookies. Open the reel in that browser once (to refresh the session), "
                "make sure the account can see it, then retry. Updating yt-dlp often fixes this: ./install.sh")
        return ReelError(f"could not download: {msg.splitlines()[-1][:200]}\n{hint}")
    return ReelError(f"could not download: {msg.splitlines()[-1][:300]}")


def fetch_audio(url: str, cookies_browser: str | None = None, cookies_file: str | None = None,
                out: Path | None = None, refresh: bool = False) -> Path:
    """Download the soundtrack of a reel as .m4a (cached). Returns the audio path."""
    url_c = canonical(url)
    key = short_hash(url_c, 12)
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    meta_p = MUSIC_DIR / f"{key}.json"
    cached = [p for p in MUSIC_DIR.glob(f"{key}.*") if p.suffix.lower() in AUDIO_EXT]
    if cached and not refresh:
        audio = cached[0]
        meta = read_json(meta_p, {}) or {}
        log(f"using cached audio: {meta.get('label') or audio.name}")
    else:
        for p in cached:
            p.unlink()
        cookies = _cookie_opts(cookies_browser, cookies_file)
        opts = {
            **cookies,
            "format": "bestaudio/best",
            "outtmpl": str(MUSIC_DIR / f"{key}.%(ext)s"),
            "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "m4a", "preferredquality": "0"}],
            "keepvideo": False,
        }
        log(f"downloading audio from {url_c}")
        try:
            with _ydl(opts) as ydl:
                info = ydl.extract_info(url_c, download=True)
        except Exception as e:  # yt_dlp.utils.DownloadError and friends
            raise _friendly(e, bool(cookies)) from None
        if info and info.get("_type") == "playlist" and info.get("entries"):
            info = next((e for e in info["entries"] if e), info)
        found = [p for p in MUSIC_DIR.glob(f"{key}.*") if p.suffix.lower() in AUDIO_EXT]
        if not found:
            raise ReelError("download finished but no audio file was produced (the reel may have no sound)")
        audio = found[0]
        meta = _describe(info or {}, url_c)
        write_json(meta_p, meta)
        log(f"saved: {meta['label']} ({meta.get('duration') or '?'}s)")
    if out:
        out = out.expanduser()
        if out.suffix == "":
            out = out / f"{_slug(meta.get('label') or key)}{audio.suffix}"
        out.parent.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copy2(audio, out)
        return out
    return audio


def _describe(info: dict, url: str) -> dict:
    """Keep only what helps you find the same sound in the Instagram app."""
    track = info.get("track") or info.get("alt_title")
    artist = info.get("artist") or info.get("creator")
    uploader = info.get("uploader") or info.get("channel") or info.get("uploader_id")
    if track and artist:
        label = f"{artist} - {track}"
    elif track:
        label = track
    else:
        label = f"Original audio - {uploader}" if uploader else (info.get("title") or "reel audio")
    return {"url": url, "label": label, "track": track, "artist": artist, "uploader": uploader,
            "duration": round(float(info.get("duration") or 0), 1) or None,
            "title": (info.get("title") or "")[:120]}


def audio_meta(path: Path) -> dict:
    """Metadata for an audio file downloaded by fetch_audio (empty if not one)."""
    p = Path(path)
    if p.parent.resolve() == MUSIC_DIR.resolve():
        return read_json(MUSIC_DIR / f"{p.stem}.json", {}) or {}
    return {}


def fetch_video(url: str, dest: Path, cookies_browser: str | None = None, cookies_file: str | None = None) -> Path:
    """Download the full reel video (used by `learn`). Cached by URL."""
    url_c = canonical(url)
    key = f"ref_{short_hash(url_c)}"
    dest.mkdir(parents=True, exist_ok=True)
    got = [p for p in dest.glob(f"{key}.*") if not p.name.endswith(".part")]
    if got:
        return got[0]
    cookies = _cookie_opts(cookies_browser, cookies_file)
    opts = {**cookies, "format": "bestvideo*+bestaudio/best", "merge_output_format": "mp4",
            "outtmpl": str(dest / f"{key}.%(ext)s")}
    log(f"downloading {url_c}")
    try:
        with _ydl(opts) as ydl:
            ydl.extract_info(url_c, download=True)
    except Exception as e:
        raise _friendly(e, bool(cookies)) from None
    got = [p for p in dest.glob(f"{key}.*") if not p.name.endswith(".part")]
    if not got:
        raise ReelError("download produced no file")
    return got[0]


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._ -]+", "", s).strip().replace(" ", "_")[:80] or "audio"
