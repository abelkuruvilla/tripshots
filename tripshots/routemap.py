"""Animated travel-route map layer, rendered with HyperFrames (HTML -> video, headless Chrome).

Optional: needs Node.js 22+. The first use installs a small private Node project in
~/.tripshots/hyperframes (hyperframes, gsap, world-atlas). Everything is offline and
deterministic: the basemap is Natural Earth land + borders (world-atlas), projected here in
Python and baked into an SVG; the route, pins and labels are animated with GSAP in HTML.
HyperFrames renders the card as transparent PNG frames that render.py lays over the footage.

Two kinds of map overlay (plan["overlays"] items with "type": "map"):
  intro    a large card early in the reel: the route draws itself stop to stop on the beat
  tracker  a small corner card for most of the reel: a dot jumps to where the current shot was taken
"""
from __future__ import annotations

import hashlib
import html
import json
import math
import os
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np

from .config import HOME, OUT_FPS
from .util import ReelError, log

RUNTIME = HOME / "hyperframes"
LAYER_CACHE = HOME / "cache" / "maps"
FONTS = Path(__file__).parent / "fonts"
PINNED = {"hyperframes": "0.8.191", "gsap": "3.12.5", "world-atlas": "2.0.2", "sane-topojson": "4.0.0"}
LAYER_VERSION = "m4"
MARGIN = 40  # transparent margin around the card (room for its shadow)

THEMES = {
    "dark": {"card": "rgba(12,18,26,0.86)", "ocean": "#0c1824", "land": "#1e2d3a", "coast": "#3d566b",
             "border": "#5d7891", "river": "#2c5674", "grid": "rgba(255,255,255,0.05)", "route": "#ffd60a", "route_glow": "rgba(255,214,10,0.55)",
             "ghost": "rgba(255,255,255,0.22)", "pin": "#ffffff", "pin_ring": "#ffd60a", "text": "#ffffff",
             "muted": "rgba(255,255,255,0.65)", "accent": "#ffd60a", "label_bg": "rgba(8,12,18,0.72)"},
    "light": {"card": "rgba(247,243,234,0.94)", "ocean": "#cfe2ea", "land": "#efe8d8", "coast": "#9fb8c2",
              "border": "#a8977a", "river": "#a9c7d3", "grid": "rgba(30,60,80,0.06)", "route": "#e4572e", "route_glow": "rgba(228,87,46,0.35)",
              "ghost": "rgba(60,60,60,0.25)", "pin": "#ffffff", "pin_ring": "#e4572e", "text": "#1d1d1b",
              "muted": "rgba(29,29,27,0.6)", "accent": "#e4572e", "label_bg": "rgba(255,255,255,0.85)"},
}


# ================================================================ runtime
def _node() -> str | None:
    cands = [shutil.which("node"), "/opt/homebrew/bin/node", "/usr/local/bin/node"]
    for c in cands:
        if c and Path(c).exists():
            try:
                v = subprocess.run([c, "-v"], capture_output=True, text=True, timeout=10).stdout.strip()
                if int(v.lstrip("v").split(".")[0]) >= 22:
                    return c
            except Exception:
                continue
    return None


def runtime_status() -> dict:
    node = _node()
    ok = (RUNTIME / "node_modules" / "hyperframes" / "package.json").exists()
    return {"node": node, "installed": ok, "dir": str(RUNTIME)}


def ensure_runtime(install: bool = True) -> Path:
    """Node project with pinned hyperframes + gsap + world-atlas. Raises ReelError with a fix."""
    node = _node()
    if not node:
        raise ReelError("the route map needs Node.js 22 or newer: `brew install node`, then run again")
    hf = RUNTIME / "node_modules" / "hyperframes" / "package.json"
    if hf.exists() and all((RUNTIME / "node_modules" / k).exists() for k in PINNED):
        return RUNTIME
    if not install:
        raise ReelError("route map runtime not installed: run `tripshots maps --setup`")
    RUNTIME.mkdir(parents=True, exist_ok=True)
    (RUNTIME / "package.json").write_text(json.dumps(
        {"name": "tripshots-maps", "private": True, "dependencies": PINNED}, indent=2))
    npm = str(Path(node).with_name("npm"))
    if not Path(npm).exists():
        npm = shutil.which("npm") or "npm"
    log("installing the route-map runtime (HyperFrames, one time, ~100 MB)...")
    env = {**os.environ, "DO_NOT_TRACK": "1", "PATH": f"{Path(node).parent}:{os.environ.get('PATH', '')}"}
    p = subprocess.run([npm, "install", "--no-audit", "--no-fund", "--loglevel=error"], cwd=RUNTIME,
                       capture_output=True, text=True, env=env)
    if p.returncode != 0:
        raise ReelError(f"npm install failed: {p.stderr[-800:]}")
    return RUNTIME


def _hf_env(node: str) -> dict:
    env = {**os.environ, "DO_NOT_TRACK": "1", "HYPERFRAMES_NO_UPDATE_CHECK": "1",
           "PATH": f"{Path(node).parent}:{os.environ.get('PATH', '')}"}
    if not env.get("HYPERFRAMES_BROWSER_PATH"):
        for c in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",):
            if Path(c).exists():
                env["HYPERFRAMES_BROWSER_PATH"] = c
                break
    return env


# ================================================================ geography
def haversine(a, b) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(min(1.0, h)))


def build_stops(shots: list[dict], max_stops: int = 7) -> list[dict]:
    """Chronological stops from the shots' GPS: nearby shots merge into one stop."""
    pts = [s for s in shots if s.get("gps") and abs(s["gps"][0]) <= 85]
    if not pts:
        return []
    pts.sort(key=lambda s: (str(s.get("created") or "~"), s["id"]))
    lat = [s["gps"][0] for s in pts]
    lon = [s["gps"][1] for s in pts]
    extent = haversine((min(lat), min(lon)), (max(lat), max(lon)))
    r = max(3.0, 0.04 * extent)
    stops: list[dict] = []
    for s in pts:
        g = (float(s["gps"][0]), float(s["gps"][1]))
        hit = next((st for st in stops if haversine(st["ll"], g) <= r), None)
        if hit is None:
            stops.append({"ll": g, "n": 1, "shots": [s["id"]]})
        else:  # running mean
            n = hit["n"]
            hit["ll"] = ((hit["ll"][0] * n + g[0]) / (n + 1), (hit["ll"][1] * n + g[1]) / (n + 1))
            hit["n"] = n + 1
            hit["shots"].append(s["id"])
    while len(stops) > max_stops:  # merge the closest consecutive pair
        k = min(range(len(stops) - 1), key=lambda i: haversine(stops[i]["ll"], stops[i + 1]["ll"]))
        a, b = stops[k], stops[k + 1]
        n = a["n"] + b["n"]
        keep = a if a["n"] >= b["n"] else b
        stops[k] = {"ll": keep["ll"], "n": n, "shots": a["shots"] + b["shots"]}
        del stops[k + 1]
    return stops


def name_stops(stops: list[dict], geocode=None) -> None:
    from .geo import place_name
    geocode = geocode or place_name
    for st in stops:
        full = geocode(*st["ll"]) or ""
        parts = [p.strip() for p in full.split(",") if p.strip()]
        st["name"] = parts[0] if parts else f"{st['ll'][0]:.2f}, {st['ll'][1]:.2f}"
        st["region"] = parts[-1] if len(parts) > 1 else ""


def _merc(lat, lon):
    lat = np.clip(lat, -85.0, 85.0)
    x = (np.asarray(lon) + 180.0) / 360.0
    y = (1 - np.log(np.tan(np.radians(lat)) + 1 / np.cos(np.radians(lat))) / math.pi) / 2
    return x, y


class Topo:
    """Minimal TopoJSON reader: polygons (with holes), lines and shared borders per object."""

    def __init__(self, path: Path):
        d = json.loads(Path(path).read_text())
        sx, sy = d["transform"]["scale"]
        tx, ty = d["transform"]["translate"]
        self.objects = d["objects"]
        self.arcs = []
        for a in d["arcs"]:
            q = np.cumsum(np.asarray(a, np.float64), axis=0)
            self.arcs.append(np.stack([q[:, 0] * sx + tx, q[:, 1] * sy + ty], 1))  # lon, lat
        self.abox = np.array([(a[:, 0].min(), a[:, 1].min(), a[:, 0].max(), a[:, 1].max()) for a in self.arcs])

    def _geoms(self, name):
        obj = self.objects.get(name) or {}
        return obj.get("geometries", [obj]) if obj.get("type") == "GeometryCollection" else [obj]

    def _ring(self, arc_ids):
        pts = []
        for i in arc_ids:
            a = self.arcs[i] if i >= 0 else self.arcs[~i][::-1]
            pts.append(a if not pts else a[1:])
        return np.concatenate(pts) if pts else np.zeros((0, 2))

    def bbox_of(self, arc_ids):
        idx = [i if i >= 0 else ~i for i in arc_ids]
        b = self.abox[idx]
        return b[:, 0].min(), b[:, 1].min(), b[:, 2].max(), b[:, 3].max()

    def polygons(self, name):
        """[(rings: [outer, hole, ...] as lon/lat arrays, bbox)]"""
        out = []
        for g in self._geoms(name):
            polys = [g["arcs"]] if g.get("type") == "Polygon" else g.get("arcs", []) if g.get("type") == "MultiPolygon" else []
            for poly in polys:
                if not poly:
                    continue
                flat = [i for r in poly for i in r]
                out.append(([self._ring(r) for r in poly], self.bbox_of(flat)))
        return out

    def lines(self, name):
        out = []
        for g in self._geoms(name):
            parts = [g["arcs"]] if g.get("type") == "LineString" else g.get("arcs", []) if g.get("type") == "MultiLineString" else []
            for part in parts:
                out.append((self._ring(part), self.bbox_of(part)))
        return out

    def borders(self, name):
        """Arcs shared by two or more geometries of an object (internal borders)."""
        use: dict[int, set] = {}

        def walk(arcs, gid):
            for x in arcs:
                if isinstance(x, list):
                    walk(x, gid)
                else:
                    use.setdefault(x if x >= 0 else ~x, set()).add(gid)
        for k, g in enumerate(self._geoms(name)):
            walk(g.get("arcs", []), k)
        ids = [i for i, s in use.items() if len(s) >= 2]
        return [(self.arcs[i], tuple(self.abox[i])) for i in ids]


_TOPO: dict = {}


def _data(name: str) -> Topo:
    files = {"world10": ("world-atlas", "countries-10m.json"), "sane50": ("sane-topojson", "dist/world_50m.json")}
    if name not in _TOPO:
        pkg, f = files[name]
        p = RUNTIME / "node_modules" / pkg / f
        if not p.exists():
            raise ReelError("map data missing: run `tripshots maps --setup`")
        _TOPO[name] = Topo(p)
    return _TOPO[name]


def topo() -> Topo:
    return _data("world10")


class View:
    """Web-Mercator view fitted to a set of points inside a w x h box."""

    def __init__(self, lls: list[tuple], w: int, h: int, pad: float = 0.22, min_km: float = 60.0):
        lat = np.array([p[0] for p in lls])
        lon = np.array([p[1] for p in lls])
        self.lon0 = float(np.mean(lon))
        x, y = _merc(lat, lon)
        cx, cy = (x.min() + x.max()) / 2, (y.min() + y.max()) / 2
        spanx, spany = max(x.max() - x.min(), 1e-9), max(y.max() - y.min(), 1e-9)
        # at least min_km across (so a single town still shows its coast / borders)
        km_per_unit = 40075.0 * math.cos(math.radians(float(np.mean(lat))))
        min_span = min_km / km_per_unit
        spanx, spany = max(spanx, min_span), max(spany, min_span * h / w)
        scale = min(w * (1 - 2 * pad) / spanx, h * (1 - 2 * pad) / spany)
        self.k, self.cx, self.cy, self.w, self.h = scale, cx, cy, w, h
        self.km_across = w / scale * km_per_unit

    def xy(self, lat, lon):
        x, y = _merc(np.asarray(lat, np.float64), np.asarray(lon, np.float64))
        return (x - self.cx) * self.k + self.w / 2, (y - self.cy) * self.k + self.h / 2

    def lonlat_bounds(self, margin=0.3):
        def inv(px, py):
            x = (px - self.w / 2) / self.k + self.cx
            y = (py - self.h / 2) / self.k + self.cy
            return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y)))), x * 360 - 180
        mw, mh = self.w * margin, self.h * margin
        la0, lo0 = inv(-mw, self.h + mh)
        la1, lo1 = inv(self.w + mw, -mh)
        return lo0, la0, lo1, la1

    def shift_for(self, b):
        """Whole-feature longitude shift (0 / ±360) that brings a feature next to the view."""
        c = (b[0] + b[2]) / 2
        return min((0.0, 360.0, -360.0), key=lambda s: abs(c + s - self.lon0))


def _svg_d(geom, closed: bool) -> str:
    from shapely.geometry import LineString, MultiLineString, MultiPolygon, Polygon
    out = []

    def ring(coords):
        c = list(coords)
        if len(c) < (3 if closed else 2):
            return ""
        return "M" + "L".join(f"{x:.1f} {y:.1f}" for x, y in c) + ("Z" if closed else "")
    gs = getattr(geom, "geoms", [geom])
    for g in gs:
        if isinstance(g, Polygon) and closed:
            out.append(ring(g.exterior.coords))
            out += [ring(r.coords) for r in g.interiors]
        elif isinstance(g, (LineString,)) and not closed:
            out.append(ring(g.coords))
        elif isinstance(g, (MultiPolygon, MultiLineString)) or hasattr(g, "geoms"):
            out.append(_svg_d(g, closed))
    return "".join(out)


def _clip_polys(view: View, polys, tol=0.6) -> str:
    from shapely import make_valid
    from shapely.geometry import Polygon, box
    lo0, la0, lo1, la1 = view.lonlat_bounds()
    m = 40
    win = box(-m, -m, view.w + m, view.h + m)
    parts = []
    for rings, b in polys:
        sh = view.shift_for(b)
        if b[2] + sh < lo0 or b[0] + sh > lo1 or b[3] < la0 or b[1] > la1:
            continue
        pr = []
        for r in rings:
            if len(r) < 4:
                continue
            px, py = view.xy(r[:, 1], r[:, 0] + sh)
            pr.append(np.stack([px, py], 1))
        if not pr:
            continue
        try:
            g = Polygon(pr[0], pr[1:])
            if not g.is_valid:
                g = make_valid(g)
            g = g.intersection(win)
        except Exception:
            continue
        if not g.is_empty:
            parts.append(_svg_d(g.simplify(tol), True))
    return "".join(parts)


def _clip_lines(view: View, lines, tol=0.8) -> str:
    from shapely.geometry import LineString, box
    lo0, la0, lo1, la1 = view.lonlat_bounds()
    win = box(-20, -20, view.w + 20, view.h + 20)
    parts = []
    for arr, b in lines:
        sh = view.shift_for(b)
        if len(arr) < 2 or b[2] + sh < lo0 or b[0] + sh > lo1 or b[3] < la0 or b[1] > la1:
            continue
        px, py = view.xy(arr[:, 1], arr[:, 0] + sh)
        g = LineString(np.stack([px, py], 1)).intersection(win)
        if not g.is_empty:
            parts.append(_svg_d(g.simplify(tol), False))
    return "".join(parts)


def basemap_svg(view: View, th: dict) -> str:
    """Ocean, land, lakes, rivers, country + state/province borders and a light graticule."""
    W10, S50 = topo(), _data("sane50")
    w, h = view.w, view.h
    land = _clip_polys(view, W10.polygons("land"))
    lakes = _clip_polys(view, S50.polygons("lakes"))
    rivers = _clip_lines(view, S50.lines("rivers")) if view.km_across < 3000 else ""
    countries = _clip_lines(view, W10.borders("countries"), tol=1.0)
    states = _clip_lines(view, S50.borders("subunits"), tol=1.0) if view.km_across < 4000 else ""
    lo0, la0, lo1, la1 = view.lonlat_bounds(0)
    step = next((s for s in (0.25, 0.5, 1, 2, 5, 10, 20, 30) if (lo1 - lo0) / s <= 6), 30)
    grid = []
    for lon in np.arange(math.floor(lo0 / step) * step, lo1 + step, step):
        px, _ = view.xy(np.array([la0]), np.array([lon]))
        if 0 < px[0] < w:
            grid.append(f"M{px[0]:.1f} 0V{h}")
    for lat in np.arange(math.floor(la0 / step) * step, la1 + step, step):
        _, py = view.xy(np.array([lat]), np.array([lo0]))
        if abs(lat) <= 84 and 0 < py[0] < h:
            grid.append(f"M0 {py[0]:.1f}H{w}")
    return (f'<rect width="{w}" height="{h}" fill="{th["ocean"]}"/>'
            f'<path d="{"".join(grid)}" fill="none" stroke="{th["grid"]}" stroke-width="1"/>'
            f'<path d="{land}" fill="{th["land"]}" stroke="{th["coast"]}" stroke-width="1.6" '
            f'stroke-linejoin="round" fill-rule="evenodd"/>'
            f'<path d="{lakes}" fill="{th["ocean"]}" stroke="{th["coast"]}" stroke-width="1" fill-rule="evenodd"/>'
            f'<path d="{rivers}" fill="none" stroke="{th["river"]}" stroke-width="1.4" stroke-linecap="round"/>'
            f'<path d="{states}" fill="none" stroke="{th["border"]}" stroke-width="1" stroke-dasharray="2 5" '
            f'stroke-linecap="round" opacity="0.8"/>'
            f'<path d="{countries}" fill="none" stroke="{th["border"]}" stroke-width="1.6" stroke-dasharray="7 5" '
            f'stroke-linecap="round"/>')


def _leg_path(a, b, bend=0.18) -> str:
    """A gently curved leg from a to b (quadratic Bezier, bulging to one side)."""
    (x0, y0), (x1, y1) = a, b
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    dx, dy = x1 - x0, y1 - y0
    L = math.hypot(dx, dy) or 1
    cx, cy = mx - dy / L * L * bend, my + dx / L * L * bend
    return f"M{x0:.1f} {y0:.1f}Q{cx:.1f} {cy:.1f} {x1:.1f} {y1:.1f}"


def _label_positions(pts, names, w, h, size):
    """Put each name right/left/above/below its pin without overlapping the others."""
    placed, out = [], []
    for (x, y), name in zip(pts, names):
        tw, thh = 0.62 * size * len(name) + 26, size + 16
        best = None
        for side in ("right", "left", "above", "below"):
            if side == "right":
                bx, by = x + 22, y - thh / 2
            elif side == "left":
                bx, by = x - 22 - tw, y - thh / 2
            elif side == "above":
                bx, by = x - tw / 2, y - 24 - thh
            else:
                bx, by = x - tw / 2, y + 24
            box = (bx, by, bx + tw, by + thh)
            inside = box[0] >= 8 and box[1] >= 8 and box[2] <= w - 8 and box[3] <= h - 8
            clash = any(not (box[2] < p[0] or box[0] > p[2] or box[3] < p[1] or box[1] > p[3]) for p in placed)
            score = (0 if inside else 2) + (0 if not clash else 1)
            if best is None or score < best[0]:
                best = (score, side, box)
            if score == 0:
                break
        placed.append(best[2])
        out.append((best[1], best[2]))
    return out


def _font_faces() -> str:
    return ("@font-face{font-family:'Anton';src:url('assets/fonts/Anton-Regular.ttf')}"
            "@font-face{font-family:'Montserrat';src:url('assets/fonts/Montserrat.ttf');font-weight:100 900}")


def trip_title(stops: list[dict]) -> str:
    regs = list(dict.fromkeys(s.get("region") for s in stops if s.get("region")))
    if not regs:
        return stops[0]["name"] if stops else ""
    return " · ".join(regs) if len(regs) <= 3 else f"{regs[0]} · {regs[1]} & more"


def fmt_km(km: float) -> str:
    return f"{km:,.0f} KM" if km >= 10 else f"{km:.1f} KM"


# ================================================================ compositions
def _head(W, H, th, extra_css=""):
    return f"""<!doctype html>
<html><head><meta charset="utf-8">
<style>{_font_faces()}
html,body{{margin:0;padding:0;background:transparent}}
#root{{position:relative;width:{W}px;height:{H}px;overflow:hidden;font-family:'Montserrat',sans-serif}}
.card{{position:absolute;left:{MARGIN}px;top:{MARGIN}px;width:{W - 2 * MARGIN}px;height:{H - 2 * MARGIN}px;
  border-radius:34px;background:{th['card']};box-shadow:0 18px 44px rgba(0,0,0,0.45);overflow:hidden;opacity:0}}
.lbl{{position:absolute;white-space:nowrap;font-weight:800;letter-spacing:0.08em;text-transform:uppercase;
  color:{th['text']};background:{th['label_bg']};border-radius:10px;padding:6px 12px;opacity:0}}
{extra_css}
</style>
<script src="assets/gsap.min.js"></script><script src="assets/MotionPathPlugin.min.js"></script>
</head><body>"""


INTRO_SIZE = (1000, 1000)


def intro_schedule(n_stops: int, beats_local: list[float], dur: float) -> tuple[float, list[float]]:
    """When the intro card's first pin pops, and when the route reaches each next stop (local s).
    Shared with the sound design so pin pops sound exactly when they appear."""
    t_out = dur - 0.4
    n_leg = max(0, n_stops - 1)
    first_pin = 0.55
    if not n_leg:
        return first_pin, []
    cand = [b for b in beats_local if first_pin + 0.3 < b < t_out - 0.5]
    span_end = t_out - 0.55
    if len(cand) >= n_leg:  # land each stop on a beat, evenly spread over the available beats
        idx = np.linspace(0, len(cand) - 1, n_leg).round().astype(int)
        arrive = [cand[i] for i in idx]
    else:
        arrive = list(np.linspace(first_pin + 0.6, span_end, n_leg))
    return first_pin, [float(max(a, first_pin + 0.35 * (k + 1))) for k, a in enumerate(arrive)]


def intro_html(stops: list[dict], beats_local: list[float], dur: float, theme: str, title: str) -> tuple[str, tuple]:
    th = THEMES[theme]
    W, H = INTRO_SIZE            # composition incl. margin
    cw = W - 2 * MARGIN
    head_h = 150
    mw, mh = cw - 40, H - 2 * MARGIN - head_h - 20
    view = View([s["ll"] for s in stops], mw, mh, pad=0.2, min_km=80 if len(stops) > 1 else 400)
    pts = [tuple(float(v) for v in view.xy(s["ll"][0], s["ll"][1])) for s in stops]
    km = sum(haversine(stops[i]["ll"], stops[i + 1]["ll"]) for i in range(len(stops) - 1))
    names = [s["name"] for s in stops]
    lsize = 24
    lpos = _label_positions(pts, names, mw, mh, lsize)
    base = basemap_svg(view, th)

    # timing: card in, then one leg per beat gap (>= 0.35 s), stats at the end, card out
    t_in, t_out = 0.45, dur - 0.4
    n_leg = max(0, len(stops) - 1)
    first_pin, arrive = intro_schedule(len(stops), beats_local, dur)
    legs = [_leg_path(pts[i], pts[i + 1], 0.16 if i % 2 == 0 else -0.16) for i in range(n_leg)]

    pins, labels = [], []
    for i, ((x, y), (side, box)) in enumerate(zip(pts, lpos)):
        pins.append(f'<g id="pin{i}" transform="translate({x:.1f},{y:.1f})"><g class="pinb">'
                    f'<circle r="20" fill="{th["route_glow"]}" opacity="0.5"/>'
                    f'<circle r="11" fill="{th["pin"]}" stroke="{th["pin_ring"]}" stroke-width="5"/></g></g>')
        labels.append(f'<div class="lbl" id="lb{i}" style="left:{20 + box[0]:.0f}px;top:{head_h + box[1]:.0f}px;'
                      f'font-size:{lsize}px">{html.escape(names[i])}</div>')
    leg_svg = "".join(
        f'<path id="ghost{i}" d="{d}" fill="none" stroke="{th["ghost"]}" stroke-width="4" stroke-dasharray="2 12" '
        f'stroke-linecap="round"/>'
        f'<path id="leg{i}" d="{d}" fill="none" stroke="{th["route"]}" stroke-width="7" stroke-linecap="round" '
        f'filter="url(#glow)" opacity="0"/>' for i, d in enumerate(legs))
    stats = f"{len(stops)} STOPS · {fmt_km(km)}" if len(stops) > 1 else ""
    sub = html.escape(title or trip_title(stops))
    css = f"""
.head{{position:absolute;left:34px;top:30px;right:34px;height:{head_h - 30}px}}
.kick{{font-weight:800;font-size:22px;letter-spacing:0.32em;color:{th['accent']};opacity:0}}
.ttl{{font-family:'Anton',sans-serif;font-size:58px;line-height:1.05;color:{th['text']};letter-spacing:0.01em;
  margin-top:6px;opacity:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.stats{{position:absolute;right:0;top:2px;font-weight:700;font-size:22px;letter-spacing:0.14em;color:{th['muted']};opacity:0}}
.map{{position:absolute;left:20px;top:{head_h}px;width:{mw}px;height:{mh}px;border-radius:22px;overflow:hidden}}
#head{{position:absolute;opacity:0}}
"""
    body = f"""
<div id="root" data-composition-id="root" data-width="{W}" data-height="{H}" data-start="0" data-duration="{dur:.3f}">
 <div id="card" class="card clip" data-start="0" data-duration="{dur:.3f}">
  <div class="head"><div class="kick" id="kick">THE ROUTE</div><div class="ttl" id="ttl">{sub}</div>
   <div class="stats" id="stats">{html.escape(stats)}</div></div>
  <div class="map"><div id="mapin" style="width:{mw}px;height:{mh}px"><svg width="{mw}" height="{mh}" viewBox="0 0 {mw} {mh}">
   <defs><filter id="glow" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="5" result="b"/>
    <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>
   <g id="cam">{base}{leg_svg}{''.join(pins)}
    <circle id="headdot" r="9" fill="{th['pin']}" stroke="{th['route']}" stroke-width="4" opacity="0"/></g>
  </svg></div></div>
  {''.join(labels)}
 </div>
<script>
gsap.registerPlugin(MotionPathPlugin);
const tl = gsap.timeline({{paused:true}});
const ARR = {json.dumps([round(a, 3) for a in arrive])};
tl.fromTo("#card", {{opacity:0, y:70, scale:0.93}}, {{opacity:1, y:0, scale:1, duration:{t_in}, ease:"power3.out"}}, 0);
tl.fromTo("#kick", {{opacity:0, y:12}}, {{opacity:1, y:0, duration:0.35, ease:"power2.out"}}, 0.18);
tl.fromTo("#ttl", {{opacity:0, y:18}}, {{opacity:1, y:0, duration:0.4, ease:"power3.out"}}, 0.26);
tl.fromTo("#mapin", {{scale:1.12}}, {{scale:1.0, duration:{first_pin}, ease:"power3.out", transformOrigin:"50% 50%"}}, 0);
function pop(i, t) {{
  tl.fromTo("#pin"+i+" .pinb", {{scale:0}}, {{scale:1, duration:0.42, ease:"back.out(2.6)", transformOrigin:"50% 50%"}}, t);
  tl.fromTo("#lb"+i, {{opacity:0, y:10}}, {{opacity:1, y:0, duration:0.3, ease:"power2.out"}}, t + 0.06);
}}
gsap.set("[id^=pin] .pinb", {{scale:0, transformOrigin:"50% 50%"}});
pop(0, {first_pin});
for (let i = 0; i < ARR.length; i++) {{
  const p = document.getElementById("leg"+i), L = p.getTotalLength();
  const t0 = i === 0 ? {first_pin} + 0.18 : ARR[i-1] + 0.05, d = Math.max(0.25, ARR[i] - t0);
  gsap.set(p, {{strokeDasharray: L, strokeDashoffset: L}});
  tl.set(p, {{opacity: 1}}, t0);
  tl.fromTo(p, {{strokeDashoffset: L}}, {{strokeDashoffset: 0, duration: d, ease: "power1.inOut", immediateRender: false}}, t0);
  tl.set("#headdot", {{opacity:1}}, t0);
  tl.to("#headdot", {{duration: d, ease: "power1.inOut", motionPath: {{path: p, align: p, alignOrigin: [0.5, 0.5]}}}}, t0);
  pop(i+1, ARR[i]);
}}
if (ARR.length) tl.fromTo("#headdot", {{opacity:1}}, {{opacity:0, duration:0.15, immediateRender:false}}, ARR[ARR.length-1]);
tl.fromTo("#stats", {{opacity:0, x:16}}, {{opacity:1, x:0, duration:0.35, ease:"power2.out"}}, {(arrive[-1] if arrive else first_pin) + 0.15:.3f});
tl.fromTo("#card", {{opacity:1, y:0, scale:1}}, {{opacity:0, y:-30, scale:0.97, duration:0.35, ease:"power2.in", immediateRender:false}}, {t_out:.3f});
window.__timelines = window.__timelines || {{}}; window.__timelines["root"] = tl;
</script>
</div></body></html>"""
    return _head(W, H, th, css) + body, (W, H)


def tracker_html(stops: list[dict], keys: list[tuple[float, int]], dur: float, theme: str) -> tuple[str, tuple]:
    """keys: (local time, stop index) whenever the footage moves to another stop."""
    th = THEMES[theme]
    W = 440
    cw = W - 2 * MARGIN
    mw = mh = cw - 24
    H = mh + 12 + 60 + 2 * MARGIN
    view = View([s["ll"] for s in stops], mw, mh, pad=0.2, min_km=60 if len(stops) > 1 else 300)
    pts = [tuple(float(v) for v in view.xy(s["ll"][0], s["ll"][1])) for s in stops]
    base = basemap_svg(view, th)
    legs = "".join(f'<path d="{_leg_path(pts[i], pts[i + 1], 0.16 if i % 2 == 0 else -0.16)}" fill="none" '
                   f'stroke="{th["route"]}" stroke-width="4" stroke-linecap="round" opacity="0.85"/>'
                   for i in range(len(pts) - 1))
    dots = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5.5" fill="{th["pin"]}" stroke="{th["route"]}" '
                   f'stroke-width="2.5"/>' for x, y in pts)
    names = "".join(f'<div class="nm" id="nm{i}">{html.escape(s["name"])}</div>' for i, s in enumerate(stops))
    k0 = keys[0][1] if keys else 0
    css = f"""
.map{{position:absolute;left:12px;top:12px;width:{mw}px;height:{mh}px;border-radius:24px;overflow:hidden}}
.nm{{position:absolute;left:14px;right:14px;top:{mh + 18}px;text-align:center;font-weight:800;font-size:23px;
  letter-spacing:0.12em;text-transform:uppercase;color:{th['text']};opacity:0;white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis}}
"""
    moves = [(round(t, 3), i) for t, i in keys]
    body = f"""
<div id="root" data-composition-id="root" data-width="{W}" data-height="{H}" data-start="0" data-duration="{dur:.3f}">
 <div id="card" class="card clip" data-start="0" data-duration="{dur:.3f}">
  <div class="map"><svg width="{mw}" height="{mh}" viewBox="0 0 {mw} {mh}">{base}{legs}{dots}
   <circle id="halo" cx="0" cy="0" r="16" fill="{th['route_glow']}"/>
   <circle id="me" cx="0" cy="0" r="9" fill="{th['route']}" stroke="{th['pin']}" stroke-width="3"/></svg></div>
  {names}
 </div>
<script>
const tl = gsap.timeline({{paused:true}});
const P = {json.dumps([[round(x, 1), round(y, 1)] for x, y in pts])}, M0 = {json.dumps(moves)}, K0 = {k0};
// every frame is computed from the timeline time alone, so render workers can seek in any order
const M = []; {{ let c = K0; for (const [t, i] of M0) {{ if (i !== c) {{ M.push([t, c, i]); c = i; }} }} }}
const me = document.getElementById("me"), halo = document.getElementById("halo");
const names = P.map((_, i) => document.getElementById("nm" + i));
const clamp = (x) => Math.max(0, Math.min(1, x)), ease = (x) => x < .5 ? 2*x*x : 1 - Math.pow(-2*x + 2, 2) / 2;
function frame(t) {{
  let x = P[K0][0], y = P[K0][1], hs = 1, ho = 1;
  const op = names.map(() => 0); let dy = 0;
  op[K0] = clamp((t - 0.15) / 0.3);
  for (const [t0, a, b] of M) {{
    if (t < t0) break;
    const q = ease(clamp((t - t0) / 0.5));
    x = P[a][0] + (P[b][0] - P[a][0]) * q; y = P[a][1] + (P[b][1] - P[a][1]) * q;
    op[a] = Math.min(op[a], 1 - clamp((t - t0) / 0.18));
    op[b] = clamp((t - t0 - 0.2) / 0.28); dy = 8 * (1 - op[b]);
    const h = (t - t0 - 0.45) / 0.6;
    if (h >= 0 && h <= 1) {{ hs = 1 + 0.9 * (1 - Math.pow(1 - h, 2)); ho = 1 - h; }} else {{ hs = 1; ho = 1; }}
  }}
  gsap.set([me, halo], {{x: x, y: y}});
  gsap.set(halo, {{scale: hs, opacity: ho, transformOrigin: "50% 50%"}});
  names.forEach((n, i) => gsap.set(n, {{opacity: op[i], y: op[i] > 0 && op[i] < 1 ? dy : 0}}));
}}
frame(0);
tl.eventCallback("onUpdate", () => frame(tl.time()));
tl.fromTo("#card", {{opacity:0, x:-24}}, {{opacity:1, x:0, duration:0.4, ease:"power3.out"}}, 0);
tl.fromTo("#card", {{opacity:1}}, {{opacity:0, duration:0.3, immediateRender:false}}, {max(0.5, dur - 0.32):.3f});
window.__timelines = window.__timelines || {{}}; window.__timelines["root"] = tl;
</script>
</div></body></html>"""
    return _head(W, H, th, css) + body, (W, H)


# ================================================================ rendering
def overlay_html(ov: dict) -> tuple[str, tuple]:
    """The HyperFrames composition for a map overlay (built from its data at render time)."""
    stops = [{"name": s["name"], "region": s.get("region", ""), "ll": tuple(s["ll"])} for s in ov["stops"]]
    theme = ov.get("theme") if ov.get("theme") in THEMES else "dark"
    if ov.get("mode") == "tracker":
        return tracker_html(stops, [(float(t), int(k)) for t, k in ov.get("keys") or [[0, 0]]],
                            float(ov["duration"]), theme)
    return intro_html(stops, [float(b) for b in ov.get("beats") or []], float(ov["duration"]), theme,
                      ov.get("title") or "")


def _place(ov: dict) -> tuple[int, int]:
    if ov.get("mode") == "tracker":
        return 14, 200
    return (1080 - INTRO_SIZE[0]) // 2, 1060 - INTRO_SIZE[1] // 2


def render_layer(ov: dict) -> Path:
    """Render one map overlay to transparent PNG frames (cached). Returns the frames folder."""
    rt = ensure_runtime()
    node = _node()
    page = ov.get("html") or overlay_html(ov)[0]
    key = hashlib.sha1((LAYER_VERSION + page + str(OUT_FPS)).encode()).hexdigest()[:16]
    proj = LAYER_CACHE / key
    frames = proj / "frames"
    want = int(round(float(ov["duration"]) * OUT_FPS))
    if frames.exists() and len(list(frames.glob("*.png"))) >= want:
        return frames
    if proj.exists():
        shutil.rmtree(proj)
    (proj / "assets" / "fonts").mkdir(parents=True)
    nm = rt / "node_modules"
    shutil.copy(nm / "gsap" / "dist" / "gsap.min.js", proj / "assets")
    shutil.copy(nm / "gsap" / "dist" / "MotionPathPlugin.min.js", proj / "assets")
    for f in ("Anton-Regular.ttf", "Montserrat.ttf"):
        shutil.copy(FONTS / f, proj / "assets" / "fonts")
    (proj / "index.html").write_text(page)
    cli = nm / "hyperframes" / "bin" / "hyperframes.mjs"
    log(f"drawing the route map ({ov.get('mode')}, {ov['duration']:.1f}s) with HyperFrames...")
    cmd = [node, str(cli), "render", str(proj), "--format", "png-sequence", "-o", str(frames), "--quiet",
           "-f", str(OUT_FPS)]
    for attempt in range(2):
        # second attempt: one worker, the most conservative capture mode
        p = subprocess.run(cmd + (["-w", "1", "--low-memory-mode"] if attempt else []), cwd=proj,
                           capture_output=True, text=True, env=_hf_env(node), timeout=1800)
        got = sorted(frames.glob("*.png")) if frames.exists() else []
        if len(got) >= want - 1:
            return frames
        (proj / f"render-{attempt}.log").write_text(re.sub(r"\x1b\[[0-9;]*m", "", p.stdout + p.stderr))
        log(f"  map render attempt {attempt + 1} failed (exit {p.returncode}, {len(got)}/{want} frames)")
        shutil.rmtree(frames, ignore_errors=True)
    errs = [l for l in (proj / "render-1.log").read_text().splitlines() if re.search(r"error|fail", l, re.I)]
    raise ReelError("HyperFrames could not render the map: " + (" | ".join(errs[-4:]) or "see " + str(proj)))


class MapLayer:
    """Lays rendered map frames over the reel (alpha blend at the overlay's position)."""

    def __init__(self, plan: dict):
        import cv2  # noqa: F401
        self.items = []
        for ov in plan.get("overlays", []):
            if ov.get("type") != "map":
                continue
            try:
                fr = render_layer(ov)
            except ReelError as e:
                log(f"route map skipped: {e}")
                continue
            files = sorted(fr.glob("*.png"))
            self.items.append({"start": float(ov["start"]), "files": files, "x": int(ov["x"]), "y": int(ov["y"])})

    def draw(self, frame: np.ndarray, t: float) -> np.ndarray:
        import cv2
        for it in self.items:
            k = int(round((t - it["start"]) * OUT_FPS))
            if not 0 <= k < len(it["files"]):
                continue
            im = cv2.imread(str(it["files"][k]), cv2.IMREAD_UNCHANGED)
            if im is None or im.shape[2] < 4 or not im[..., 3].any():
                continue
            h, w = im.shape[:2]
            x, y = it["x"], it["y"]
            x0, y0 = max(0, x), max(0, y)
            x1, y1 = min(frame.shape[1], x + w), min(frame.shape[0], y + h)
            if x1 <= x0 or y1 <= y0:
                continue
            src = im[y0 - y:y1 - y, x0 - x:x1 - x]
            a = src[..., 3:4].astype(np.float32) / 255.0
            rgb = src[..., 2::-1].astype(np.float32)
            roi = frame[y0:y1, x0:x1].astype(np.float32)
            if not frame.flags.writeable:
                frame = frame.copy()
            frame[y0:y1, x0:x1] = (roi * (1 - a) + rgb * a + 0.5).astype(np.uint8)
        return frame


# ================================================================ planning
def plan_route_map(plan: dict, shots: list[dict], by_id: dict, cfg: dict, geocode=None) -> list[dict]:
    """Add map overlays to the plan. cfg: {mode: intro|tracker|both|off, theme: auto|dark|light, title}"""
    mode = str(cfg.get("mode") or "off")
    if mode in ("off", "none", "false", "False"):
        return []
    stops = build_stops(shots, int(cfg.get("max_stops", 7)))
    if not stops:
        log("route map: none of the footage has GPS, so there's no route to draw")
        return []
    name_stops(stops, geocode)
    theme = cfg.get("theme") or "auto"
    if theme == "auto":
        preset = (plan.get("text") or {}).get("preset", "bold")
        theme = "light" if preset in ("editorial", "minimal", "typewriter") else "dark"
    slim = [{"name": s["name"], "region": s.get("region", ""), "ll": [round(v, 5) for v in s["ll"]]} for s in stops]
    segs = plan["segments"]
    total = float(plan["duration"])
    beats = [float(b) for b in plan.get("beats") or []]
    texts = [o for o in plan["overlays"] if o["type"] in ("hook", "location", "cta")]
    added = []
    intro_end = None

    if mode in ("intro", "both"):
        # the first stretch, starting on a cut after the opening text, where no other text is on screen
        early = [o for o in texts if o["start"] < 4.0]
        after = max([o["start"] + o["duration"] for o in early] or [0.6])
        want = float(cfg.get("duration", 3.4 if len(stops) > 1 else 2.6)) + 0.4 * max(0, len(stops) - 4)
        # location titles may give way: the map names the places anyway
        busy = [(o["start"], o["start"] + o["duration"]) for o in texts if o["type"] != "location"]
        start = end = None
        for sg in segs:
            st0 = sg["out_start"]
            if st0 < after - 0.05:
                continue
            ends = [x["out_start"] + x["dur"] for x in segs if x["out_start"] + x["dur"] >= st0 + want - 0.3]
            en = min(ends[0] if ends else total - 0.4, st0 + want + 1.2, total - 0.4)
            if en - st0 >= 2.0 and not any(a < en and st0 < b for a, b in busy):
                start, end = st0, en
                break
        if start is not None:
            clash = [o for o in plan["overlays"] if o["type"] == "location"
                     and o["start"] < end and start < o["start"] + o["duration"]]
            for o in clash:
                plan["overlays"].remove(o)
            texts = [o for o in texts if o not in clash]
            if clash:
                log(f"route map: the map card replaces {len(clash)} location title(s) at that moment")
        if start is None:
            log("route map: no free moment for the map card between the titles (try --no-location or a longer reel)")
        else:
            if end - start >= 2.0:
                dur = round(end - start, 3)
                local_beats = [round(b - start, 3) for b in beats if start < b < end]
                ov = {"type": "map", "mode": "intro", "text": "route map", "start": round(start, 3), "duration": dur,
                      "theme": theme, "title": cfg.get("title") or "", "beats": local_beats, "stops": slim}
                ov["x"], ov["y"] = _place(ov)
                plan["overlays"].append(ov)
                added.append(ov)
                intro_end = end
    if mode in ("tracker", "both") and len(stops) >= 1:
        start = intro_end if intro_end else max([o["start"] + o["duration"] for o in texts if o["start"] < 4.0]
                                                or [0.3])
        cta = min([o["start"] for o in texts if o["type"] == "cta"] or [total])
        end = min(total - 0.2, cta - 0.1)
        if end - start >= 2.0:
            def stop_of(seg):
                sid = seg.get("shot_id") or (seg.get("clips") or [{}])[0].get("shot_id")
                g = by_id.get(sid, {}).get("gps")
                if not g:
                    return None
                return min(range(len(stops)), key=lambda i: haversine(stops[i]["ll"], g))
            keys, cur = [], None
            for s in segs:
                k = stop_of(s)
                if k is None or k == cur:
                    continue
                t = max(0.0, s["out_start"] - start)
                if s["out_start"] + s["dur"] <= start:
                    cur = k
                    keys = [(0.0, k)]
                    continue
                if t < end - start - 0.6:
                    keys.append((round(t, 3), k))
                    cur = k
            if not keys:
                keys = [(0.0, 0)]
            dur = round(end - start, 3)
            ov = {"type": "map", "mode": "tracker", "text": "route tracker", "start": round(start, 3), "duration": dur,
                  "theme": theme, "keys": [[t, k] for t, k in keys], "stops": slim}
            ov["x"], ov["y"] = _place(ov)
            plan["overlays"].append(ov)
            added.append(ov)
    if added:
        names = " → ".join(s["name"] for s in stops)
        log(f"route map: {len(stops)} stop(s): {names}")
    return added
