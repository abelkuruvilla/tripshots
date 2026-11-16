"""Post a finished reel through Upload-Post (upload-post.com), now or at a set time:
`tripshots post NAME.mp4 --platforms instagram,tiktok [--at 2026-12-01T18:00 --tz Europe/Madrid] [--send]`.

Nothing leaves the computer without `--send`: without it, it shows what it would post. It posts only a reel
whose quality checks passed (NAME.qa.json; `--force` to post one that didn't), with the caption written for it
(NAME.caption.txt) and the hook as the title. The same video to the same accounts at the same time is never sent
twice: the request carries an idempotency key (from the file, its size and time, the user, the platforms and the
schedule) and every post is remembered in ~/.tripshots/posted.json.
Settings (in ~/.tripshots/.env): UPLOAD_POST_KEY (the API key), UPLOAD_POST_USER (the profile name set up on
upload-post.com), UPLOAD_POST_API (another address, for testing).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

from .config import HOME
from .util import ReelError, log, read_json, write_json

API = "https://api.upload-post.com"
PLATFORMS = ("instagram", "tiktok", "youtube", "facebook", "x", "threads", "linkedin", "pinterest", "bluesky")
POSTED = HOME / "posted.json"


def _video(path: Path) -> Path:
    p = Path(path).expanduser().resolve()
    if p.name.endswith(".plan.json"):
        p = p.with_name(p.name.replace(".plan.json", ".mp4"))
    if not p.is_file() or p.suffix.lower() != ".mp4":
        raise ReelError(f"no rendered reel at {p} (render it first)")
    return p


def prepare(video: Path, platforms: list[str], at: str | None = None, tz: str | None = None,
            title: str | None = None, force: bool = False) -> dict:
    """What would be posted, after every check; raises when it shouldn't be."""
    v = _video(video)
    plats = [p.strip().lower() for p in platforms if p.strip()]
    bad = [p for p in plats if p not in PLATFORMS]
    if not plats or bad:
        raise ReelError(f"platforms: one or more of {', '.join(PLATFORMS)}" + (f" (not {', '.join(bad)})" if bad else ""))
    if tz and not at:
        raise ReelError("--tz goes with --at (the time it is for)")
    if at:
        try:
            when = datetime.fromisoformat(at)
        except ValueError:
            raise ReelError(f"--at wants a date and time like 2026-12-01T18:00 (got {at})")
        if when.tzinfo is None and not tz:
            log("no --tz: Upload-Post reads the time as UTC")
    base = v.with_suffix("")
    qa = read_json(Path(f"{base}.qa.json"))
    if qa is None and not force:
        raise ReelError("this reel has no quality report: run `tripshots qa` on it first (or --force)")
    failed = [c["check"] for c in (qa or {}).get("checks") or [] if not c.get("ok")]
    if failed and not force:
        raise ReelError(f"its quality checks didn't all pass ({', '.join(failed)}): fix them, or post with --force")
    plan = read_json(Path(f"{base}.plan.json")) or {}
    cap = Path(f"{base}.caption.txt")
    caption = cap.read_text().strip() if cap.exists() else ""
    hook = next((o.get("text") for o in plan.get("overlays") or [] if o.get("type") == "hook" and o.get("text")), None)
    title = (title or hook or (caption.splitlines()[0] if caption else "") or v.stem).strip()
    if len(title) > 100:  # (a whole word last)
        title = title[:98].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    if "youtube" in plats and not title.strip():
        raise ReelError("YouTube needs a title (--title)")
    user = os.environ.get("UPLOAD_POST_USER", "")
    st = v.stat()
    key = hashlib.sha256(f"{v.name}:{st.st_size}:{int(st.st_mtime)}:{user}:{','.join(sorted(plats))}:{at or ''}:{tz or ''}"
                         .encode()).hexdigest()[:32]
    return {"video": str(v), "platforms": plats, "title": title, "description": caption, "at": at, "tz": tz,
            "user": user, "key": key, "qa_failed": failed}


def _multipart(fields: list[tuple[str, str]], file_field: str, file: Path) -> tuple[bytes, str]:
    bound = uuid.uuid4().hex
    out = []
    for k, v in fields:
        out.append(f"--{bound}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
    out.append(f"--{bound}\r\nContent-Disposition: form-data; name=\"{file_field}\"; filename=\"{file.name}\"\r\n"
               "Content-Type: video/mp4\r\n\r\n".encode())
    out.append(file.read_bytes())
    out.append(f"\r\n--{bound}--\r\n".encode())
    return b"".join(out), f"multipart/form-data; boundary={bound}"


def post(video: Path, platforms: list[str], at: str | None = None, tz: str | None = None, title: str | None = None,
         send: bool = False, force: bool = False, again: bool = False) -> dict:
    job = prepare(video, platforms, at, tz, title, force)
    done = read_json(POSTED, {}) or {}
    if job["key"] in done and not again:
        return {**job, "sent": False, "note": f"already posted on {done[job['key']].get('at_time')} "
                                              f"(request {done[job['key']].get('request_id')}); --again to post it anyway"}
    if not send:
        return {**job, "sent": False, "note": "dry run: nothing was sent (add --send to post)"}
    api_key = os.environ.get("UPLOAD_POST_KEY")
    if not api_key or not job["user"]:
        raise ReelError("set UPLOAD_POST_KEY and UPLOAD_POST_USER in ~/.tripshots/.env (from upload-post.com)")
    fields = [("user", job["user"]), ("title", job["title"]), ("description", job["description"] or job["title"]),
              ("async_upload", "true")] + [("platform[]", p) for p in job["platforms"]]
    if at:
        fields.append(("scheduled_date", at))
    if tz:
        fields.append(("timezone", tz))
    body, ctype = _multipart(fields, "video", Path(job["video"]))
    url = (os.environ.get("UPLOAD_POST_API") or API).rstrip("/") + "/api/upload"
    if not re.match(r"https?://", url):
        raise ReelError(f"UPLOAD_POST_API must be an http(s) address (got {url})")
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": f"Apikey {api_key}", "Content-Type": ctype, "Idempotency-Key": job["key"]})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            res = json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raise ReelError(f"Upload-Post refused it ({e.code}): {e.read().decode(errors='ignore')[:300]}")
    except urllib.error.URLError as e:
        raise ReelError(f"could not reach Upload-Post: {e.reason}")
    rid = res.get("request_id") or res.get("job_id")
    done[job["key"]] = {"video": job["video"], "platforms": job["platforms"], "at": at, "tz": tz,
                        "request_id": rid, "at_time": datetime.now().isoformat(timespec="seconds")}
    write_json(POSTED, done)
    log(f"posted to {', '.join(job['platforms'])}" + (f" for {at}" + (f" {tz}" if tz else "") if at else "")
        + (f" (request {rid}: progress at upload-post.com)" if rid else ""))
    return {**job, "sent": True, "response": res}
