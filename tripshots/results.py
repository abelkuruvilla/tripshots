"""How your reels actually did, and what that says about the next one.

`tripshots results add NAME.mp4 --views 1200 --avg-watch 6.1 --sends 14 --saves 9` records a reel's numbers
(from Instagram's Insights, or Edits' "sends per reach"). `tripshots results sync` reads them from the Instagram
Graph API instead (a professional account; INSTAGRAM_ACCESS_TOKEN and INSTAGRAM_USER_ID), matching posts to
your reels by their caption. Each result keeps the reel's ideas (format, hook type, style, length, whether
you appear early) from its plan, and `preferences()` turns them into a lean: which format and hook type have
held viewers and been sent the most. `make --format auto` and `--variants` use it once there is enough data.

The score per reel: 60 % how much of it people watched (average watch time / length, capped at 1) and 40 %
sends per view (scaled so 2 % is a full mark): the two things Instagram's own guidance points at.
Stored in ~/.tripshots/results.json.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

from .config import HOME
from .util import ReelError, log, read_json, write_json

STORE = HOME / "results.json"
GRAPH = "https://graph.facebook.com/v21.0"


def load() -> list[dict]:
    return read_json(STORE, []) or []


def _save(rows: list[dict]) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    write_json(STORE, rows)


def _plan_for(path: Path) -> tuple[Path | None, dict]:
    p = Path(path).expanduser()
    if p.name.endswith(".plan.json"):
        plan_p = p
    else:
        plan_p = p.with_name(p.name.rsplit(".", 1)[0] + ".plan.json")
    return (plan_p, read_json(plan_p, {}) or {}) if plan_p.exists() else (None, {})


def features(plan: dict) -> dict:
    """The reel's ideas, as recorded in its plan."""
    segs = plan.get("segments") or []
    st = plan.get("story") or {}
    hook = next((o["text"] for o in plan.get("overlays") or [] if o["type"] == "hook"), None)
    early = any(s.get("people") for s in segs if s["out_start"] < 3)
    return {"style": plan.get("style"), "format": st.get("format") or ("story" if st else "even"),
            "hook_type": st.get("hook_type"), "hook": hook, "duration": plan.get("duration"),
            "shots": len(segs), "arc": bool(st.get("arc")), "people_early": bool(early) or None,
            "words": (plan.get("words") or {}).get("kind")} if plan else {}


def reel_score(m: dict, duration: float | None) -> float | None:
    views = float(m.get("views") or m.get("plays") or m.get("reach") or 0)
    watch = m.get("avg_watch")
    if not views or watch is None or not duration:
        return None
    w = min(1.0, float(watch) / float(duration))
    sends = float(m.get("sends") or 0) / views
    return round(0.6 * w + 0.4 * min(1.0, sends / 0.02), 3)


def add(reel: str | Path, metrics: dict, posted: str | None = None, media_id: str | None = None) -> dict:
    rows = load()
    plan_p, plan = _plan_for(Path(reel))
    key = str(Path(reel).expanduser().resolve())
    row = next((r for r in rows if r.get("reel") == key or (media_id and r.get("media_id") == media_id)), None)
    if row is None:
        row = {"reel": key, "added": datetime.now().isoformat(timespec="seconds")}
        rows.append(row)
    row.update({"plan": str(plan_p) if plan_p else row.get("plan"), "features": features(plan) or row.get("features", {}),
                "metrics": {**row.get("metrics", {}), **{k: v for k, v in metrics.items() if v is not None}}})
    if posted:
        row["posted"] = posted
    if media_id:
        row["media_id"] = media_id
    row["score"] = reel_score(row["metrics"], (row.get("features") or {}).get("duration"))
    _save(rows)
    return row


def preferences(min_n: int = 2) -> dict:
    """The format and hook type with the best average score (with a pull towards the overall mean, so one lucky
    reel doesn't decide). confident = at least min_n reels for the winner and 5 scored overall."""
    rows = [r for r in load() if r.get("score") is not None]
    if not rows:
        return {}
    mean = sum(r["score"] for r in rows) / len(rows)
    out: dict = {"n": len(rows), "mean": round(mean, 3)}
    for feat in ("format", "hook_type"):
        groups: dict = {}
        for r in rows:
            v = (r.get("features") or {}).get(feat)
            if v:
                groups.setdefault(v, []).append(r["score"])
        if not groups:
            continue
        shrunk = {v: (sum(xs) + 2 * mean) / (len(xs) + 2) for v, xs in groups.items()}
        best = max(shrunk, key=shrunk.get)
        out[feat] = best
        out[f"{feat}_scores"] = {v: round(x, 3) for v, x in sorted(shrunk.items(), key=lambda kv: -kv[1])}
        out[f"{feat}_n"] = {v: len(xs) for v, xs in groups.items()}
    out["confident"] = len(rows) >= 5 and (out.get("format_n") or {}).get(out.get("format"), 0) >= min_n
    return out


# ---------------------------------------------------------------- Instagram Graph API
def _get(path: str, params: dict) -> dict:
    url = f"{GRAPH}/{path}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="ignore")[:300]
        raise ReelError(f"Instagram API: {e.code} {body}") from None


def _insights(mid: str, token: str) -> dict:
    wanted = ["views", "reach", "shares", "saved", "likes", "comments", "ig_reels_avg_watch_time"]
    while wanted:
        try:
            data = _get(f"{mid}/insights", {"metric": ",".join(wanted), "access_token": token})
            vals = {d["name"]: (d.get("values") or [{}])[0].get("value") for d in data.get("data", [])}
            return {"views": vals.get("views"), "reach": vals.get("reach"), "sends": vals.get("shares"),
                    "saves": vals.get("saved"), "likes": vals.get("likes"), "comments": vals.get("comments"),
                    "avg_watch": (vals["ig_reels_avg_watch_time"] / 1000.0) if vals.get("ig_reels_avg_watch_time")
                    else None}
        except ReelError as e:
            bad = [m for m in wanted if m in str(e)]
            if not bad:
                raise
            wanted = [m for m in wanted if m not in bad]
    return {}


def _local_reels(roots: list[Path]) -> list[tuple[Path, str]]:
    out = []
    for root in roots:
        for cap in Path(root).expanduser().glob("**/*.caption.txt"):
            mp4 = cap.with_name(cap.name.replace(".caption.txt", ".mp4"))
            if mp4.exists():
                out.append((mp4, cap.read_text()))
    return out


def sync(roots: list[Path] | None = None, limit: int = 50) -> list[dict]:
    """Fetch your recent reels' insights and match them to the reels TripShots made (by caption)."""
    token, uid = os.environ.get("INSTAGRAM_ACCESS_TOKEN"), os.environ.get("INSTAGRAM_USER_ID")
    if not token or not uid:
        raise ReelError("set INSTAGRAM_ACCESS_TOKEN and INSTAGRAM_USER_ID (a professional account's Graph API "
                        "token; see docs/storytelling.md), or record numbers with `tripshots results add`")
    from .pipeline import default_out_dir
    roots = roots or [default_out_dir()]
    local = _local_reels(roots)
    media = _get(f"{uid}/media", {"fields": "id,caption,media_product_type,timestamp,permalink", "limit": limit,
                                  "access_token": token}).get("data", [])
    got = []
    for m in media:
        if m.get("media_product_type") not in ("REELS", None):
            continue
        cap = (m.get("caption") or "").strip()
        best, best_r = None, 0.0
        for mp4, text in local:
            r = SequenceMatcher(None, cap[:300].lower(), text[:300].lower()).ratio()
            if r > best_r:
                best, best_r = mp4, r
        if not best or best_r < 0.55:
            continue
        row = add(best, _insights(m["id"], token), posted=m.get("timestamp"), media_id=m["id"])
        row["permalink"] = m.get("permalink")
        got.append(row)
    if got:
        rows = load()
        for g in got:
            for r in rows:
                if r.get("reel") == g["reel"]:
                    r["permalink"] = g.get("permalink")
        _save(rows)
    log(f"results: {len(got)} reel(s) matched to your Instagram posts")
    return got
