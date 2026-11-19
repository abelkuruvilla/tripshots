"""Page layouts: every shot of the reel set on a page instead of filling the frame (two trend formats).

  print   "this trend as a photographer": each shot is a photographic print on paper, a word or two above it
          (or across the top of an upright print) and two small captions under its corners (where, when). Cut on
          the beat, no movement: a gallery wall turning page by page.
  route   "a clip per place": each shot sits in a wide window at the top, the place's name under it, and under
          that the whole trip's route on a map with a pin on the stop this shot was filmed at. The pin jumps
          stop to stop as the reel moves on: a road trip in one glance.

The plan carries `page` {kind, paper/theme, stops (route)}; each paged segment carries `page` {title, left, right}
(print) or {stop, label} (route). render.py renders a paged shot at its window's size and places it on the page
(`_box`), shot_frame keeps it still and lays this module's furniture (words, map) over it. Upright reels only.
"""
from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .config import CANVAS
from .util import log

KINDS = ("print", "route")
FONTS = Path(__file__).parent / "fonts"
PAPERS = {"white": (250, 250, 248), "cream": (244, 238, 226), "black": (12, 12, 12)}
INK = {"white": (24, 24, 22), "cream": (40, 34, 28), "black": (236, 236, 232)}
ROUTE = {"light": {"bg": (8, 8, 8), "ocean": (200, 228, 236), "land": (232, 238, 224), "coast": (160, 190, 196),
                   "border": (176, 170, 156), "route": (40, 104, 226), "pin": (226, 56, 48), "text": (240, 240, 240)},
         "dark": {"bg": (8, 8, 8), "ocean": (14, 26, 38), "land": (34, 48, 60), "coast": (70, 96, 118),
                  "border": (96, 120, 140), "route": (255, 214, 10), "pin": (255, 255, 255), "text": (240, 240, 240)}}

# a word or two for a print, from what the AI saw (only clear scenes: a wrong word is worse than none)
TITLES = {"mountains": "The Peaks", "water": "The Water", "beach": "The Coast", "forest": "The Forest",
          "desert": "The Desert", "snow": "The Snow", "sky": "The Sky", "night": "The Night", "cityscape": "The City",
          "street": "The Streets", "landscape": "The Land", "aerial": "From Above", "wildlife": "The Wild",
          "food": "The Food", "transport": "The Road", "portrait": "The Traveller", "people": "The Traveller"}


def _font(name: str, size: int, weight: int | None = None) -> ImageFont.FreeTypeFont:
    try:
        f = ImageFont.truetype(str(FONTS / name), size)
    except OSError:
        return ImageFont.load_default()
    if weight:   # a variable font (Montserrat, Playfair): its default is the lightest
        try:
            f.set_variation_by_axes([weight])
        except Exception:
            pass
    return f


# ---------------------------------------------------------------- geometry
def upright_print(seg: dict) -> bool:
    w, h = float(seg.get("src_w") or 16), float(seg.get("src_h") or 9)
    return w <= h * 1.15


def box(plan: dict, seg: dict) -> list | None:
    """[w, h, x, y, colour] of the shot's window on the page, or None for a shot not on a page."""
    pg, sp = plan.get("page") or {}, seg.get("page")
    if pg.get("kind") not in KINDS or not isinstance(sp, dict) or seg.get("panel") or CANVAS.horizontal:
        return None
    W, H = CANVAS.w, CANVAS.h
    even = lambda v: int(round(v / 2)) * 2   # noqa: E731
    if pg["kind"] == "print":
        bg = "#%02x%02x%02x" % PAPERS.get(pg.get("paper"), PAPERS["white"])
        bw = even(W * 0.77)
        if upright_print(seg):
            bh = even(bw * 1.5)
            return [bw, bh, (W - bw) // 2, even(H * 0.12), bg]
        bh = even(bw / 1.5)
        return [bw, bh, (W - bw) // 2, even(H * 0.29), bg]
    bh = even(W / 1.62)
    return [W, bh, 0, even(H * 0.118), "#%02x%02x%02x" % ROUTE["light"]["bg"]]


# ---------------------------------------------------------------- what lies over the page
def furniture(plan: dict, seg: dict) -> np.ndarray | None:
    """The page's words (and map) for one shot as an RGBA layer the size of the frame, or None."""
    b = box(plan, seg)
    if not b:
        return None
    pg, sp = plan["page"], seg["page"]
    if pg["kind"] == "print":
        return _print_layer(tuple(b[:4]), pg.get("paper") or "white", upright_print(seg), str(sp.get("title") or ""),
                            str(sp.get("left") or ""), str(sp.get("right") or ""), CANVAS.size)
    stops = tuple((round(float(s["ll"][0]), 4), round(float(s["ll"][1]), 4)) for s in pg.get("stops") or [])
    return _route_layer(tuple(b[:4]), pg.get("theme") or "light", stops, int(sp.get("stop", -1)),
                        str(sp.get("label") or ""), CANVAS.size)


@lru_cache(maxsize=64)
def _print_layer(b, paper, upright, title, left, right, size) -> np.ndarray:
    W, H = size
    bw, bh, bx, by = b
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    ink = INK.get(paper, INK["white"]) + (255,)
    if title:
        f = _font("PlayfairDisplay.ttf", int(W * 0.052), 500)
        tw = d.textlength(title, font=f)
        if upright:   # across the top of the print, in white
            d.text(((W - tw) / 2, by + bh * 0.07), title, font=f, fill=(255, 255, 255, 245))
        else:         # on the paper above it
            d.text(((W - tw) / 2, by - W * 0.11), title, font=f, fill=ink)
    small = _font("PlayfairDisplay.ttf", int(W * 0.02), 500)
    y = by + bh + W * 0.012
    if left:
        d.text((bx + 2, y), left, font=small, fill=ink)
    if right:
        d.text((bx + bw - d.textlength(right, font=small) - 2, y), right, font=small, fill=ink)
    return np.asarray(im)


@lru_cache(maxsize=64)
def _route_layer(b, theme, stops, at, label, size) -> np.ndarray:
    W, H = size
    bw, bh, bx, by = b
    th = ROUTE.get(theme, ROUTE["light"])
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    if label:
        f = _font("Montserrat.ttf", int(W * 0.03), 600)
        d.text(((W - d.textlength(label, font=f)) / 2, by + bh + H * 0.024), label, font=f, fill=th["text"] + (255,))
    my, mh = int(H * 0.544), int(H * 0.343)
    if len(stops) >= 1:
        im.paste(Image.fromarray(_map(stops, theme, W, mh)), (0, my))
        pts = _stop_xy(stops, W, mh)
        d = ImageDraw.Draw(im)
        line = [(x, y + my) for x, y in pts]
        if len(line) > 1:
            d.line(line, fill=th["route"] + (255,), width=max(3, W // 200), joint="curve")
        r = max(5, W // 140)
        for x, y in line:
            d.ellipse((x - r, y - r, x + r, y + r), fill=th["route"] + (255,), outline=(255, 255, 255, 255), width=2)
        if 0 <= at < len(line):   # the pin on this shot's stop
            x, y = line[at]
            R = r * 2.4
            d.ellipse((x - R, y - 2.6 * R, x + R, y - 0.6 * R), fill=th["pin"] + (255,), outline=(255, 255, 255, 255),
                      width=3)
            d.polygon([(x - R * 0.62, y - 1.1 * R), (x + R * 0.62, y - 1.1 * R), (x, y)], fill=th["pin"] + (255,))
            d.ellipse((x - R * 0.35, y - 1.95 * R, x + R * 0.35, y - 1.25 * R), fill=(255, 255, 255, 255))
    return np.asarray(im)


def _view(stops, w, h):
    from .routemap import View
    return View(list(stops), w, h, pad=0.1, min_km=60 if len(stops) > 1 else 300)


def _stop_xy(stops, w, h):
    v = _view(stops, w, h)
    return [tuple(float(c) for c in v.xy(la, lo)) for la, lo in stops]


@lru_cache(maxsize=8)
def _map(stops, theme, w, h) -> np.ndarray:
    """The basemap under the route (Natural Earth land, lakes, borders from the route map's data), RGBA."""
    th = ROUTE.get(theme, ROUTE["light"])
    im = Image.new("RGBA", (w, h), th["ocean"] + (255,))
    d = ImageDraw.Draw(im)
    try:
        from .routemap import _data, topo
        v = _view(stops, w, h)
        lo0, la0, lo1, la1 = v.lonlat_bounds(0.3)

        def near(bb, shift):
            return not (bb[2] + shift < lo0 or bb[0] + shift > lo1 or bb[3] < la0 or bb[1] > la1)

        def xy(arr, shift):
            px, py = v.xy(arr[:, 1], arr[:, 0] + shift)
            return list(zip(px.tolist(), py.tolist()))
        for rings, bb in topo().polygons("land"):
            s = v.shift_for(bb)
            if near(bb, s) and len(rings[0]) > 2:
                d.polygon(xy(rings[0], s), fill=th["land"] + (255,), outline=th["coast"] + (255,))
                for hole in rings[1:]:
                    if len(hole) > 2:
                        d.polygon(xy(hole, s), fill=th["ocean"] + (255,))
        for rings, bb in _data("sane50").polygons("lakes"):
            s = v.shift_for(bb)
            if near(bb, s) and len(rings[0]) > 2:
                d.polygon(xy(rings[0], s), fill=th["ocean"] + (255,), outline=th["coast"] + (255,))
        lines = topo().borders("countries")
        if v.km_across < 4000:
            lines = lines + _data("sane50").borders("subunits")
        for arc, bb in lines:
            s = v.shift_for(bb)
            if near(bb, s) and len(arc) > 1:
                d.line(xy(arc, s), fill=th["border"] + (255,), width=1)
    except Exception as e:   # no map data (`tripshots maps --setup`): the route on plain colour still reads
        log(f"page map drawn without a basemap ({str(e)[:80]})")
        d.rectangle((0, 0, w, h), fill=th["land"] + (255,))
    return np.asarray(im)


def lay(frame: np.ndarray, layer: np.ndarray | None) -> np.ndarray:
    """The furniture over a frame (alpha blend)."""
    if layer is None:
        return frame
    a = layer[..., 3:4].astype(np.float32) / 255.0
    if not a.any():
        return frame
    return (frame.astype(np.float32) * (1 - a) + layer[..., :3].astype(np.float32) * a + 0.5).astype(np.uint8)


# ---------------------------------------------------------------- planning
def _when(shot: dict) -> str:
    from datetime import datetime
    from .diversity import _when as when
    t = when(shot)
    return datetime.fromtimestamp(t).strftime("%B %Y") if t else ""


def apply(plan: dict, by_id: dict, shots: list[dict] | None, kind: str, settings: dict | None = None,
          facts: list[dict] | None = None) -> list[str]:
    """Put every full-screen shot of the reel on a page of this kind. Returns what changed, in words."""
    st = settings or {}
    segs = plan.get("segments") or []
    if kind not in KINDS or CANVAS.horizontal or (plan.get("frame") or {}).get("band"):
        return []
    clear(plan)
    if facts is None:
        facts = _facts(plan, by_id, shots)
    facts = list(facts) + [{}] * (len(segs) - len(facts))
    ovs = plan.get("overlays") or []
    hook = next((o for o in ovs if o.get("type") == "hook" and str(o.get("text") or "").strip()), None)
    first = 1 if kind == "print" and hook and float(hook.get("start", 0)) < float(segs[0]["dur"]) else 0
    if kind == "print":
        plan["page"] = {"kind": "print", "paper": st.get("paper") if st.get("paper") in PAPERS else "white"}
        used = set()
        for i, sg in enumerate(segs):
            if i < first or sg.get("panel"):
                continue
            sh = by_id.get(sg.get("shot_id")) or {}
            t = TITLES.get(str((sh.get("ai") or {}).get("scene") or ""), "")
            t = "" if t in used else t
            used.add(t)
            f = facts[i]
            sg["page"] = {"title": t, "left": _short(_first(f.get("landmark")) or f.get("region"), 30),
                          "right": _when(sh)}
    else:
        from .diversity import _when as when, positions
        pos = positions(list(by_id.values()) if shots is None else shots)
        if not any(sg.get("panel") for sg in segs):
            moved = _in_time_order(segs, by_id, when)   # a clip per place, in the order filmed: the route reads
            facts = [facts[k] for k in moved]
        import bisect
        pool = [sh for sh in (by_id.values() if shots is None else shots) if sh.get("id") in pos]
        known = sorted((t, i) for i, sh in enumerate(pool) if (t := when(sh)) is not None)
        lls = [pos[sh["id"]] for sh in pool]

        def where(sg):
            """Its own position, else that of the trip's picture taken nearest in time, within three hours (a
            camera without GPS filmed where the phone was)."""
            sh = by_id.get(sg.get("shot_id")) or {}
            g = pos.get(sh.get("id"))
            t = when(sh)
            if g or t is None or not known:
                return g
            j = bisect.bisect(known, (t, -1))
            near = [known[k] for k in (j - 1, j) if 0 <= k < len(known)]
            dt, k = min((abs(t - kt), ki) for kt, ki in near)
            return lls[k] if dt <= 3 * 3600 else None
        stops: list[list[float]] = []
        at: list[int] = []
        gs = []
        for sg in segs:   # a stop per place (a place visited again is the same stop)
            g = where(sg)
            gs.append(g)
            if not g:
                at.append(-1)   # where it was filmed isn't known: no pin rather than a wrong one
                continue
            k = next((j for j, s_ in enumerate(stops) if _km(s_, g) <= 25), None)
            if k is None:
                stops.append([float(g[0]), float(g[1])])
                k = len(stops) - 1
            at.append(k)
        if len(stops) < 2:
            log("route pages need footage from two places or more (GPS)")
            return []
        plan["page"] = {"kind": "route", "theme": st.get("theme") if st.get("theme") in ROUTE else "light",
                        "stops": [{"ll": s_} for s_ in stops]}
        for i, sg in enumerate(segs):
            if sg.get("panel"):
                continue
            f = facts[i]
            own = by_id.get(sg.get("shot_id"), {}).get("gps") and not f.get("near")
            lm = _first(f.get("landmark"))
            name = lm or _first(f.get("place")) or str(f.get("region") or "")
            reg = str(f.get("region") or "")
            if not reg and gs[i] and not lm:   # the state it was filmed in, from the position borrowed above
                try:
                    from .geo import region
                    reg = region(gs[i][0], gs[i][1]) or ""
                except Exception:
                    reg = ""
                name = name or reg
            if lm and not own:
                reg = ""   # a landmark the AI saw, with a borrowed position: its state could be across a border
            label = f"{name}, {reg}" if name and reg and reg not in name else name
            sg["page"] = {"stop": at[i], "label": _short(label, 42)}
        if hook and segs and segs[0].get("page"):   # the opening line becomes the first page's caption
            segs[0]["page"]["label"] = _short(str(hook["text"]), 42)
    paged = [i for i, sg in enumerate(segs) if sg.get("page")]
    for i in paged:   # a page turns on the cut: no transition, no movement, no effect over the paper
        if i > 0 and i - 1 in paged:
            segs[i - 1].update({"trans_out": None, "trans_dur": 0.0, "trans_params": {}})
        held = {k: segs[i].pop(k) for k in SET_ASIDE if k in segs[i]}
        if held:   # back when the pages come off
            segs[i]["page"]["held"] = held
    from .fxlib import SEG_KEYS
    gone = {k for i in paged for k in (segs[i]["page"].get("held") or {})}
    if plan.get("moves"):   # the director's moves the pages set aside aren't in this reel any more
        plan["moves"] = [m for m in plan["moves"] if SEG_KEYS.get(m.get("id")) not in gone and m.get("id") != "grid_lines"]
    plan_held = {k: plan.pop(k) for k in ("grid", "freeze") if k in plan}
    if plan_held:
        plan["page"]["held"] = plan_held
    # the page carries its own words: other lettering (and the corner map) would lie across the paper. Only a hook
    # on a shot left full screen stays. Kept in the page record: they come back when the pages are taken off
    keep = []
    if first:   # the hook, over its own full-screen shot only
        end = float(segs[0]["dur"]) - float(hook.get("start", 0))
        keep = [{**hook, "duration": round(min(float(hook.get("duration", end)), end), 3), "page": True}]
    if ovs:
        plan["page"]["hidden"] = ovs
        plan["overlays"] = keep
    return [f"pages: {kind} on {len(paged)} shot(s)"]


def _first(v) -> str:
    """The name before the first comma ("Forrest Gump Point, Monument Valley" -> "Forrest Gump Point")."""
    return str(v or "").split(",")[0].strip()


def _short(v, n: int) -> str:
    """At most n characters, cut between words, never inside one."""
    v = " ".join(str(v or "").split())
    if len(v) <= n:
        return v
    cut = v[:n + 1].rsplit(" ", 1)[0].rstrip(",;:-")
    return cut if cut else v[:n]


def _facts(plan: dict, by_id: dict, shots) -> list[dict]:
    try:
        from .pipeline import _seg_facts   # (full: the exact state; a coarse one can be across the border)
        return _seg_facts(plan, by_id, list(by_id.values()) if shots is None else shots, full=True)
    except Exception:
        return [{} for _ in plan.get("segments") or []]


def _in_time_order(segs: list[dict], by_id: dict, when) -> list[int]:
    """Put the shots into the slots in the order they were filmed (each slot keeps its length and place in the
    music; a shot with no time stays where it is). Returns, per slot, the slot its shot came from."""
    from .planedit import _content, _put
    timed = [(when(by_id.get(sg.get("shot_id")) or {}), i) for i, sg in enumerate(segs)]
    idx = [i for t, i in timed if t is not None]
    order = sorted(idx, key=lambda i: timed[i][0])
    moved = list(range(len(segs)))
    if order == idx:
        return moved
    contents = [_content(sg) for sg in segs]
    for slot, src in zip(idx, order):
        moved[slot] = src
        if slot != src:
            _put(segs[slot], dict(contents[src]))
            _fit(segs[slot], by_id.get(segs[slot].get("shot_id")))
    return moved


def _fit(seg: dict, sh: dict | None) -> None:
    """A clip moved into a slot of another length: its best window for this length (planner._best_window)."""
    if not sh or seg.get("kind") != "video" or seg.get("freeze") or seg.get("ramp"):
        return
    from .planner import _best_window
    speed = float(seg.get("speed", 1.0))
    if (sh["t1"] - sh["t0"]) < float(seg["dur"]) * speed:
        speed = max(0.6, (sh["t1"] - sh["t0"]) / float(seg["dur"]))
    seg["speed"] = round(speed, 3)
    seg["in"] = round(_best_window(sh, float(seg["dur"]) * speed), 3)


def _km(a, b) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(min(1.0, h)))


# what a page sets aside: effects and moves drawn over the whole frame (they'd cover the paper)
SET_ASIDE = ("mosaic", "backdrop", "isolate", "pose", "clones", "roll", "zoompunch", "effect", "colour_in",
             "silhouette", "keys", "shake", "rgb", "black_tail")


def clear(plan: dict) -> bool:
    pg = plan.pop("page", None) or {}
    had = bool(pg)
    plan.update(pg.get("held") or {})
    for sg in plan.get("segments") or []:
        sg.update((sg.get("page") or {}).get("held") or {})
    if pg.get("hidden"):
        plan["overlays"] = [o for o in plan.get("overlays") or [] if not o.get("page")] + pg["hidden"]
    for sg in plan.get("segments") or []:
        had = bool(sg.pop("page", None)) or had
    return had
