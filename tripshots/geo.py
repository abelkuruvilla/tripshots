"""GPS -> place name ("Moraine Lake, Alberta") via OpenStreetMap Nominatim, cached on disk."""
from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request

from .config import HOME
from .util import log, read_json, write_json

CACHE = HOME / "geocode_cache.json"
_last = 0.0
_offline = False


def place_name(lat: float, lon: float) -> str | None:
    global _last, _offline
    key = f"{lat:.3f},{lon:.3f}"
    cache = read_json(CACHE, {}) or {}
    if key in cache:
        return cache[key]
    if _offline or os.environ.get("TRIPSHOTS_OFFLINE") == "1":
        return None
    wait = 1.1 - (time.time() - _last)  # Nominatim policy: max 1 request/second
    if wait > 0:
        time.sleep(wait)
    _last = time.time()
    url = "https://nominatim.openstreetmap.org/reverse?" + urllib.parse.urlencode(
        {"lat": round(lat, 3), "lon": round(lon, 3), "format": "jsonv2", "zoom": 12, "accept-language": "en"})
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "tripshots/0.1 (personal travel reels)"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
    except Exception as e:
        _offline = True
        log(f"place lookup failed ({e}); use --location \"Place, Region\" to label manually")
        return None
    a = data.get("address", {})
    local = (a.get("tourism") or a.get("natural") or a.get("leisure") or a.get("village") or a.get("town")
             or a.get("city") or a.get("municipality") or a.get("county"))
    region = a.get("state") or a.get("region") or a.get("country")
    if a.get("country_code") not in ("us", "ca", "au") and a.get("country"):
        region = a.get("country")
    name = ", ".join(x for x in dict.fromkeys([local, region]) if x) or None
    cache[key] = name
    write_json(CACHE, cache)
    return name


SEARCH_CACHE = HOME / "geocode_search.json"


def search(query: str) -> dict | None:
    """Place name -> {name, lat, lon, bbox [s, n, w, e], shape (GeoJSON, simplified)} via Nominatim,
    cached on disk. "Yellowstone" gives the park's outline, so "footage in Yellowstone" is a
    point-in-polygon test, not a guess from names."""
    global _last, _offline
    key = query.strip().lower()
    cache = read_json(SEARCH_CACHE, {}) or {}
    if key in cache:
        return cache[key]
    if _offline or os.environ.get("TRIPSHOTS_OFFLINE") == "1":
        return None
    wait = 1.1 - (time.time() - _last)
    if wait > 0:
        time.sleep(wait)
    _last = time.time()
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": query, "format": "jsonv2", "limit": 5, "polygon_geojson": 1, "polygon_threshold": 0.005,
         "accept-language": "en"})
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "tripshots/0.1 (personal travel reels)"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode())
    except Exception as e:
        _offline = True
        log(f"place search failed ({e}); matching on folder names and known place names only")
        return None
    if not data:
        cache[key] = None
        write_json(SEARCH_CACHE, cache)
        return None
    # prefer an area (park, city, region) over a point or a line (a river, a road) of the same name
    d = next((x for x in data if (x.get("geojson") or {}).get("type") in ("Polygon", "MultiPolygon")), data[0])
    s, n, w, e = (float(x) for x in d.get("boundingbox", [0, 0, 0, 0]))
    res = {"name": d.get("display_name", query), "lat": float(d["lat"]), "lon": float(d["lon"]),
           "bbox": [s, n, w, e], "type": d.get("type"), "shape": d.get("geojson")}
    cache[key] = res
    write_json(SEARCH_CACHE, cache)
    return res
