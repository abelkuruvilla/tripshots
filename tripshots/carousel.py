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

    def score(s):   # the shot's score, plus whether its subject survives the 4:5 crop and it has no words on it
        sh = by_id.get(s["shot_id"]) or {}
        from .insight import burned_in
        fit = ((sh.get("insight") or {}).get("fit") or {}).get("4:5")
        return float((sh.get("ai") or {}).get("score") or 5) + (0.6 if fit else -0.6 if fit is False else 0) \
            - 3 * burned_in(sh)
    rest = sorted(segs[1:], key=lambda s: -score(s))[:max(0, n - 1)]
    return [segs[0]] + [s for s in segs[1:] if s in rest]


def picture(seg: dict, plan: dict, size: tuple[int, int] = (W, H), crop: dict | None = None) -> np.ndarray:
    """The shot as a picture of `size`, framed at its subject and coloured as in the reel (its thumbnail if the
    source can't be read). `crop` {zoom, x, y}: zoom onto that point of the picture."""
    from .motion import apply_keys
    from .render import _source_frame
    W, H = size
    local = float(seg.get("dur", 1.0)) / 2
    frame = _source_frame(seg, local, {**(plan.get("color") or {}), "grade": plan.get("grade")}, (W, H))
    if frame is not None:
        frame = np.ascontiguousarray(frame)
        return apply_keys(frame, [{"t": 0, **crop}], 0.0) if crop else frame
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
                    out = np.ascontiguousarray(np.asarray(im.crop((x, y, x + W, y + H))))
                    return apply_keys(out, [{"t": 0, **crop}], 0.0) if crop else out
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
    import os
    from .pipeline import _seg_facts
    by_id = _shots(plan)
    facts = []
    for offline in ("1", None):   # what is already known first; the map services only when that isn't enough
        was = os.environ.get("TRIPSHOTS_OFFLINE")
        try:
            if offline:
                os.environ["TRIPSHOTS_OFFLINE"] = offline
            facts = _seg_facts(plan, by_id, list(by_id.values()), full=True)
        except Exception as e:  # offline or no positions: the titles on screen are enough
            log(f"carousel: places not looked up ({str(e)[:60]})")
            facts = []
        finally:
            if offline:
                if was is None:
                    os.environ.pop("TRIPSHOTS_OFFLINE", None)
                else:
                    os.environ["TRIPSHOTS_OFFLINE"] = was
        known = {str(f.get("landmark") or f.get("place") or "").split(",")[0] for f in facts} - {""}
        if len(known | set(names.values())) >= 2:
            break
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


LAYOUTS = {"single": 1, "duo": 2, "trio": 3}
GAP = 12


def _seg_for(plan: dict, shot_id: str) -> dict | None:
    """The shot as the reel frames it (its segment), or, for a shot not in the reel, framed from its record."""
    for s in plan.get("segments") or []:
        for c in (s.get("clips") or [s]):
            if c.get("shot_id") == shot_id and not s.get("panel"):
                return c
    from .planedit import _shots
    sh = _shots(plan).get(shot_id)
    if not sh:
        return None
    a = sh.get("ai") or {}
    e = {"shot_id": sh["id"], "kind": sh["kind"], "src": sh["src"], "src_w": sh.get("w"), "src_h": sh.get("h"),
         "subject_x": a.get("subject_x", 0.5), "layout": "crop", "thumb": sh.get("thumb"), "dur": 1.0,
         "hdr": sh.get("hdr", False), "transfer": sh.get("transfer"), "log": sh.get("log")}
    if sh["kind"] == "video":
        e["in"] = float(sh.get("t0", 0)) + max(0.0, (float(sh.get("t1", 1)) - float(sh.get("t0", 0))) / 2 - 0.5)
    else:
        e["still"] = sh.get("still") or sh["src"]
    return e


def _cells(layout: str) -> list[tuple[int, int, int, int]]:
    """The picture boxes (x, y, w, h) of a slide layout."""
    if layout == "duo":   # two stacked
        h = (H - GAP) // 2
        return [(0, 0, W, h), (0, h + GAP, W, H - h - GAP)]
    if layout == "trio":  # one wide on top, two side by side below
        h = (H - GAP) * 3 // 5
        w = (W - GAP) // 2
        return [(0, 0, W, h), (0, h + GAP, w, H - h - GAP), (w + GAP, h + GAP, W - w - GAP, H - h - GAP)]
    return [(0, 0, W, H)]


def draw_slide(sl: dict, k: int, total: int, spec: dict, plan: dict) -> np.ndarray:
    if sl["kind"] == "route":
        return _mark(recap(spec.get("places") or []), k, total, spec.get("handle"), dark=True)
    layout = sl.get("layout", "single")
    out = np.full((H, W, 3), 245, np.uint8)
    for (x, y, w, h), sid in zip(_cells(layout), sl.get("shots") or []):
        seg = _seg_for(plan, sid)
        if seg is None:
            continue
        crops = sl.get("crops") or {}
        out[y:y + h, x:x + w] = picture(seg, plan, (w, h), crops.get(sid))
    if k == 1 and spec.get("title"):
        out = cover(out, spec["title"], spec.get("sub"))
    if k > 1 or spec.get("handle"):
        out = _mark(np.ascontiguousarray(out).copy(), k, total, spec.get("handle"))
    return out


def render_spec(spec: dict, plan: dict, folder: Path) -> dict:
    """Draw every slide of a carousel spec into the folder (unchanged slides come from the cache)."""
    import hashlib
    import json
    from .framing import use_plan
    use_plan(plan)
    folder.mkdir(parents=True, exist_ok=True)
    cache = folder / ".cache"
    cache.mkdir(exist_ok=True)
    for old in folder.glob("[0-9][0-9].jpg"):
        old.unlink()
    slides = spec["slides"]
    total = len(slides)
    looks = json.dumps([plan.get("color"), plan.get("grade")], sort_keys=True, default=str)
    keep = set()
    for k, sl in enumerate(slides, 1):
        key = hashlib.sha1(json.dumps([{x: y for x, y in sl.items() if x != "file"}, k, total, spec.get("handle"), spec.get("title") if k == 1 else None,
                                       spec.get("sub") if k == 1 else None,
                                       spec.get("places") if sl["kind"] == "route" else None, looks, "s2"],
                                      sort_keys=True, default=str).encode()).hexdigest()[:16]
        cached = cache / f"{key}.jpg"
        if not cached.exists():
            log(f"carousel: slide {k}/{total}")
            Image.fromarray(draw_slide(sl, k, total, spec, plan)).save(cached, quality=92)
        keep.add(cached.name)
        f = folder / f"{k:02d}.jpg"
        f.write_bytes(cached.read_bytes())
        sl["file"] = str(f)
    for old in cache.glob("*.jpg"):
        if old.name not in keep:
            old.unlink()
    spec["checks"] = checks(spec.get("title") or "", total)
    write_json(folder / "carousel.json", spec)
    return spec


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
    slides = [{"kind": "cover" if k == 0 else "shot", "layout": "single", "shots": [s["shot_id"]]}
              for k, s in enumerate(shots)]
    if with_route:
        slides.append({"kind": "route", "places": places})
    spec = {"plan": str(plan_path), "folder": str(folder), "size": [W, H], "title": title, "sub": sub,
            "handle": handle, "places": places, "stops": stops, "slides": slides,
            "next": f"tripshots caption {plan_path} writes the words; for a carousel the caption's first line "
                    "carries the hook"}
    spec = render_spec(spec, plan, folder)
    spec["cover_text"] = title
    write_json(folder / "carousel.json", spec)
    return spec


def load(plan_path: Path) -> dict | None:
    plan_path = Path(plan_path)
    base = plan_path.name[:-len(".plan.json")] if plan_path.name.endswith(".plan.json") else plan_path.stem
    return read_json(plan_path.with_name(f"{base}.carousel") / "carousel.json")


def edit(plan_path: Path, ops: list[dict]) -> dict:
    """Change a carousel and draw it again (only the slides that changed). Slides are numbered from 1.
      {"op": "move", "from": 3, "to": 1}         {"op": "remove", "slide": 4}
      {"op": "add", "shot_id": "S040", "at": 3}  {"op": "swap", "slide": 2, "shot_id": "S040", "cell": 1}
      {"op": "layout", "slide": 2, "layout": "single|duo|trio", "shots": ["S1", "S2"]}
      {"op": "crop", "slide": 2, "cell": 1, "zoom": 1.4, "x": 0.4, "y": 0.5}
      {"op": "title", "text": "...", "sub": "..."}  {"op": "handle", "text": "nadodi_tales"}
      {"op": "route", "on": true}"""
    plan_path = Path(plan_path)
    plan = read_json(plan_path)
    spec = load(plan_path)
    if not plan or not spec:
        raise ReelError("make the carousel first (tripshots carousel PLAN)")
    slides = spec["slides"]

    def at(n, allow_end=False):
        i = int(n) - 1
        if not 0 <= i < len(slides) + (1 if allow_end else 0):
            raise ReelError(f"slide {n} doesn't exist (1..{len(slides)})")
        return i

    def known(sid):
        if _seg_for(plan, sid) is None:
            raise ReelError(f"unknown shot {sid}")
        return sid
    for o in ops:
        op = o.get("op")
        if op == "move":
            a, b = at(o["from"]), at(o["to"])
            slides.insert(b, slides.pop(a))
        elif op == "remove":
            if len(slides) <= 1:
                raise ReelError("a carousel needs at least one slide")
            slides.pop(at(o["slide"]))
        elif op == "add":
            i = at(o.get("at", len(slides) + 1), allow_end=True)
            slides.insert(i, {"kind": "shot", "layout": "single", "shots": [known(o["shot_id"])]})
        elif op == "swap":
            sl = slides[at(o["slide"])]
            if sl["kind"] == "route":
                raise ReelError("the route slide has no picture")
            c = int(o.get("cell", 1)) - 1
            shots = list(sl.get("shots") or [])
            while len(shots) <= c:
                shots.append(shots[-1] if shots else known(o["shot_id"]))
            shots[c] = known(o["shot_id"])
            sl["shots"] = shots
            (sl.get("crops") or {}).pop(shots[c], None)
        elif op == "layout":
            sl = slides[at(o["slide"])]
            lay = o.get("layout", "single")
            if lay not in LAYOUTS or sl["kind"] == "route":
                raise ReelError(f"layout is one of {', '.join(LAYOUTS)}")
            shots = [known(x) for x in (o.get("shots") or [])] or list(sl.get("shots") or [])
            if len(shots) < LAYOUTS[lay]:   # fill the new cells with the reel's best shots not on a slide yet
                from .planedit import _shots
                used = {x for s2 in slides for x in s2.get("shots") or []} | set(shots)
                reel = [s2["shot_id"] for s2 in pick(plan, 20)]
                rest = [i for i, sh in sorted(_shots(plan).items(), key=lambda kv: -float(((kv[1].get("ai") or {})
                                                                                             .get("score")) or 0))]
                extra = [x for x in dict.fromkeys(reel + rest) if x not in used]   # the reel's best first, then the trip's
                again = [x for x in dict.fromkeys(reel + rest) if x not in shots and x not in extra]  # then repeats
                shots += (extra + again)[:LAYOUTS[lay] - len(shots)]
            sl["layout"], sl["shots"] = lay, shots[:LAYOUTS[lay]]
        elif op == "crop":
            sl = slides[at(o["slide"])]
            c = int(o.get("cell", 1)) - 1
            sid = (sl.get("shots") or [None] * (c + 1))[c]
            if not sid:
                raise ReelError("no picture there")
            crops = dict(sl.get("crops") or {})
            if o.get("reset"):
                crops.pop(sid, None)
            else:
                crops[sid] = {"zoom": round(max(1.0, min(3.0, float(o.get("zoom", 1.0)))), 3),
                              "x": round(max(0.0, min(1.0, float(o.get("x", 0.5)))), 3),
                              "y": round(max(0.0, min(1.0, float(o.get("y", 0.5)))), 3)}
            sl["crops"] = crops
        elif op == "title":
            spec["title"] = str(o.get("text") or "").strip()
            if "sub" in o:
                spec["sub"] = str(o["sub"] or "").strip() or None
        elif op == "handle":
            spec["handle"] = str(o.get("text") or "").strip().lstrip("@") or None
        elif op == "route":
            has = any(s2["kind"] == "route" for s2 in slides)
            if o.get("on", True) and not has:
                if len(spec.get("places") or []) < 2:
                    raise ReelError("fewer than two places are known: no route to show")
                slides.append({"kind": "route", "places": spec["places"]})
            elif not o.get("on", True):
                spec["slides"] = slides = [s2 for s2 in slides if s2["kind"] != "route"]
        else:
            raise ReelError(f"unknown carousel op {op}")
    for k, sl in enumerate(slides):   # the first picture slide is the cover
        if sl["kind"] in ("cover", "shot"):
            sl["kind"] = "cover" if k == 0 else "shot"
    if len(slides) > 20:
        raise ReelError("Instagram takes 20 slides at most")
    return render_spec(spec, plan, Path(spec["folder"]))
