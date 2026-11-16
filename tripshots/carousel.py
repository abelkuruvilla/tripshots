"""A carousel post from a reel (`tripshots carousel NAME.plan.json`): the reel's best shots as 1080x1350 slides,
coloured like the reel, ready to upload with the reel or after it.

What makes a carousel work (as Instagram's format rewards it):
- the cover decides whether anyone swipes: one picture and a title of six words or fewer, big, kept well inside
  the frame (the profile grid crops the edges), with the place under it
- 6 to 10 slides, numbered (3/8), so people can see the end
- a last slide that stands on its own and gets saved or sent: here, the route (the places, in order)
- your handle small on every slide, because screenshots travel without you

Writes NAME.carousel/01.jpg ... and carousel.json (slides, the cover's words, checks) next to the plan.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
from PIL import Image

from .util import ReelError, log, read_json, write_json

W, H = 1080, 1350
MARGIN = 120          # the grid crop and the phone's corners: the cover's words stay inside this
MAX_WORDS = 6


def _font(text: str, name: str, size: int):
    from PIL import ImageFont
    from . import scripts, typo
    p = scripts.for_text(text)  # Malayalam, Hindi...: a font that has the letters
    return ImageFont.truetype(str(p), size) if p else typo.font(name, size)


def _latin(text: str) -> bool:
    from .scripts import script_of
    return script_of(text) is None


def pick(plan: dict, n: int) -> list[dict]:
    """The slides' shots: the reel's opening shot (its hook) as the cover, then its best other shots (by the AI's
    score), one per shot, in the reel's order. Split screens are left out."""
    from .planedit import _shots
    segs, seen = [], set()
    for s in plan.get("segments") or []:
        if s.get("panel") or not s.get("shot_id") or s["shot_id"] in seen:
            continue
        seen.add(s["shot_id"])
        segs.append(s)
    if not segs:
        return []
    by_id = _shots(plan)
    score = lambda s: float(((by_id.get(s["shot_id"]) or {}).get("ai") or {}).get("score") or 5)
    rest = sorted(segs[1:], key=lambda s: -score(s))[:max(0, n - 1)]
    return [segs[0]] + [s for s in segs[1:] if s in rest]


def picture(seg: dict, plan: dict) -> np.ndarray:
    """The shot as a 4:5 picture, framed at its subject and coloured as in the reel (its thumbnail if the
    source can't be read)."""
    from .render import _source_frame
    local = float(seg.get("dur", 1.0)) / 2
    frame = _source_frame(seg, local, {**(plan.get("color") or {}), "grade": plan.get("grade")}, (W, H))
    if frame is not None:
        return np.ascontiguousarray(frame)
    for k in ("thumb", "still", "src"):
        p = seg.get(k)
        if p and Path(p).exists() and Path(p).suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".heic"):
            try:
                with Image.open(p) as im:
                    im = im.convert("RGB")
                    s = max(W / im.width, H / im.height)
                    im = im.resize((int(im.width * s) + 1, int(im.height * s) + 1))
                    x = int(float(seg.get("subject_x", 0.5)) * (im.width - W))
                    y = (im.height - H) // 2
                    return np.asarray(im.crop((x, y, x + W, y + H)))
            except OSError:
                continue
    raise ReelError(f"no picture for shot {seg.get('shot_id')}")


def _text(frame: np.ndarray, text: str, font_name: str, size: int, x: int | None, y: int, max_w: int,
          fill=(255, 255, 255), shadow: float = 0.55, gap: float = 1.08) -> int:
    """Wrapped text at y (top), centred unless x is given (then left-aligned there); returns the block's bottom."""
    from . import typo
    fnt = _font(text, font_name, size)
    lines = typo._wrap(text.split(), fnt, max_w, fnt.getlength(" "))
    asc, desc = fnt.getmetrics()
    for ln in lines:
        sprite, pad = typo._render_text(" ".join(ln), fnt, fill=fill, shadow=shadow)
        w = sprite.shape[1] - 2 * pad
        left = (W - w) // 2 if x is None else x
        frame[:] = typo._blend(frame, sprite, left - pad, y - pad, 1.0)
        y += int((asc + desc) * gap)
    return y


def _height(text: str, font_name: str, size: int, max_w: int, gap: float = 1.08) -> int:
    from . import typo
    fnt = _font(text, font_name, size)
    asc, desc = fnt.getmetrics()
    return int(len(typo._wrap(text.split(), fnt, max_w, fnt.getlength(" "))) * (asc + desc) * gap)


def cover(frame: np.ndarray, title: str, sub: str | None) -> np.ndarray:
    """The title in the lower part of the picture, ending well above the handle and the grid's crop."""
    from . import typo
    title = title.upper() if _latin(title) else title
    w = W - 2 * MARGIN
    size = 84
    while size > 56 and _height(title, "montserrat-bold", size, w, 1.02) > 0.3 * H:
        size -= 6
    block = _height(title, "montserrat-bold", size, w, 1.02) + (18 + _height(sub, "montserrat", 40, w) if sub else 0)
    y = H - 190 - block
    out = typo._scrim(frame, (0, y, W, y + block), 0.55)
    y = _text(out, title, "montserrat-bold", size, None, y, w, gap=1.02)
    if sub:
        _text(out, sub, "montserrat", 40, None, y + 18, w, fill=(235, 235, 235))
    return out


def recap(places: list[str], title: str = "The route") -> np.ndarray:
    """The saveable last slide: the places, numbered, on paper."""
    from .popout import paper
    out = paper(W, H)
    ink = (34, 32, 30)
    y = _text(out, title.upper(), "montserrat-bold", 64, MARGIN, MARGIN + 60, W - 2 * MARGIN, fill=ink, shadow=0)
    y += 50
    step = min(110, int((H - MARGIN - 80 - y) / max(1, len(places))))
    for i, p in enumerate(places, 1):
        _text(out, f"{i:02d}", "spacemono-bold", 40, MARGIN, y + 8, 200, fill=(150, 120, 90), shadow=0)
        _text(out, p, "montserrat-bold", min(56, step - 30), MARGIN + 110, y, W - 2 * MARGIN - 110, fill=ink,
              shadow=0)
        y += step
    return out


def _mark(frame: np.ndarray, k: int, n: int, handle: str | None, dark: bool = False) -> np.ndarray:
    col = (40, 38, 36) if dark else (255, 255, 255)
    sh = 0 if dark else 0.6
    lab = f"{k}/{n}"
    from . import typo
    fw = typo.font("spacemono-bold", 30).getlength(lab)
    _text(frame, lab, "spacemono-bold", 30, int(W - 56 - fw), 48, 200, fill=col, shadow=sh)
    if handle:
        _text(frame, "@" + handle.lstrip("@"), "montserrat", 28, 56, H - 84, 600, fill=col, shadow=sh)
    return frame


def _stops(plan: dict) -> dict:
    """Where each shot was filmed, by shot id, in the reel's order: a location title on screen over it first,
    else the landmark the AI recognised, else the place from its GPS. States and countries are not stops."""
    from .planedit import _shots
    segs = plan.get("segments") or []
    names: dict = {}
    t = 0.0
    starts = []
    for s in segs:
        starts.append(t)
        t += float(s.get("dur", 0))
    for o in plan.get("overlays") or []:
        if o.get("type") in ("location", "label") and (o.get("main") or o.get("text")):
            k = max([i for i, st in enumerate(starts) if st <= float(o.get("start", 0)) + 1e-3] or [0])
            names.setdefault(segs[k].get("shot_id"), str(o.get("main") or o["text"]).split(",")[0].strip())
    try:
        from .pipeline import _seg_facts
        by_id = _shots(plan)
        facts = _seg_facts(plan, by_id, list(by_id.values()), full=True)
    except Exception as e:  # offline or no positions: the titles on screen are enough
        log(f"carousel: places not looked up ({str(e)[:60]})")
        facts = []
    regions = {str(f["region"]).lower() for f in facts if f.get("region")}
    for s, f in zip(segs, facts):
        name = str(f.get("landmark") or f.get("place") or "").split(",")[0].strip()
        if name and name.lower() not in regions:
            names.setdefault(s.get("shot_id"), name)
    return {k: v for k, v in names.items() if k and v and v.lower() not in regions}


def _route(plan: dict, stops: dict) -> list[str]:
    order = [stops[s["shot_id"]] for s in plan.get("segments") or [] if s.get("shot_id") in stops]
    return list(dict.fromkeys(order))[:8]


def checks(title: str, n: int) -> list[str]:
    out = []
    words = len(re.findall(r"\S+", title))
    if words > MAX_WORDS:
        out.append(f"the cover title is {words} words: six or fewer read at thumbnail size")
    if n < 5:
        out.append(f"{n} slides: under 5 the swipe rarely starts (the reel may have too few distinct shots)")
    return out


def make(plan_path: Path, n: int = 8, title: str | None = None, handle: str | None = None, route: bool = True,
         out_dir: Path | None = None) -> dict:
    from .framing import use_plan
    plan_path = Path(plan_path)
    plan = read_json(plan_path)
    if not plan or not plan.get("segments"):
        raise ReelError(f"could not read {plan_path}")
    use_plan(plan)
    n = max(3, min(10, int(n)))
    stops = _stops(plan)
    places = _route(plan, stops) if route else []
    with_route = len(places) >= 2
    shots = pick(plan, n - (1 if with_route else 0))
    if not shots:
        raise ReelError("the reel has no single shots to make slides from")
    hook = next((o.get("text") for o in plan.get("overlays") or [] if o.get("type") == "hook" and o.get("text")), None)
    here = stops.get(shots[0]["shot_id"])       # where the cover's own picture was taken
    title = (title or hook or here or "").strip()
    sub = here if here and here.lower() not in title.lower() else None
    base = plan_path.name[:-len(".plan.json")] if plan_path.name.endswith(".plan.json") else plan_path.stem
    folder = Path(out_dir).expanduser() if out_dir else plan_path.with_name(f"{base}.carousel")
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("[0-9][0-9].jpg"):
        old.unlink()
    total = len(shots) + (1 if with_route else 0)
    slides = []
    for k, seg in enumerate(shots, 1):
        log(f"carousel: slide {k}/{total}")
        frame = picture(seg, plan)
        if k == 1 and title:
            frame = cover(frame, title, sub)
        frame = _mark(np.ascontiguousarray(frame).copy(), k, total, handle) if k > 1 or handle else frame
        p = folder / f"{k:02d}.jpg"
        Image.fromarray(frame).save(p, quality=92)
        slides.append({"file": str(p), "shot_id": seg["shot_id"], "kind": "cover" if k == 1 else "shot"})
    if with_route:
        p = folder / f"{total:02d}.jpg"
        Image.fromarray(_mark(recap(places), total, total, handle, dark=True)).save(p, quality=92)
        slides.append({"file": str(p), "kind": "route", "places": places})
    res = {"plan": str(plan_path), "folder": str(folder), "size": [W, H], "cover_text": title, "slides": slides,
           "checks": checks(title, total),
           "next": f"tripshots caption {plan_path} writes the words; for a carousel the caption's first line "
                   "carries the hook"}
    write_json(folder / "carousel.json", res)
    return res
