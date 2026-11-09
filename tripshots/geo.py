"""GPS -> place name ("Moraine Lake, Alberta") via OpenStreetMap Nominatim, cached on disk."""
from __future__ import annotations

import json
import math
import os
import time
import urllib.parse
import urllib.request

from .config import HOME
from .util import log, read_json, write_json

CACHE = HOME / "geocode_cache.json"
_last = 0.0
_offline = False


PLACE_VERSION = "v2"  # v2: national parks and landmarks before towns and counties
OVERPASS = os.environ.get("TRIPSHOTS_OVERPASS", "https://overpass-api.de/api/interpreter")
UA = {"User-Agent": "tripshots/0.1 (personal travel reels)"}


def place_name(lat: float, lon: float) -> str | None:
    """The name a viewer would recognise for where a shot was taken:
      "Half Dome, Yosemite National Park"   a famous spot inside a park
      "Yosemite National Park, California"  inside a national park or protected area
      "Golden Gate Bridge, California"      a famous spot (one with a Wikipedia/Wikidata entry) nearby
      "Moab, Utah"                          otherwise the town (the county only when there is nothing else)
    Parks and spots come from OpenStreetMap (Overpass), towns from Nominatim. Cached on disk."""
    global _offline
    key = f"{PLACE_VERSION}:{lat:.3f},{lon:.3f}"
    cache = read_json(CACHE, {}) or {}
    if key in cache:
        return cache[key]
    if _offline or os.environ.get("TRIPSHOTS_OFFLINE") == "1":
        old = cache.get(f"{lat:.3f},{lon:.3f}")  # an earlier version's answer beats none
        return old
    addr = _nominatim(lat, lon)
    if addr is None and _offline:
        return None
    addr = addr or {}
    local = (addr.get("tourism") or addr.get("natural") or addr.get("leisure") or addr.get("village")
             or addr.get("town") or addr.get("city") or addr.get("municipality") or addr.get("hamlet")
             or addr.get("county"))
    region = addr.get("state") or addr.get("region") or addr.get("country")
    if addr.get("country_code") not in ("us", "ca", "au") and addr.get("country"):
        region = addr.get("country")
    spot, park = _landmark(lat, lon)
    if spot and park and spot != park and spot not in park:
        parts = [spot, park]
    elif park:
        parts = [park, region]
    elif spot:
        parts = [spot, region]
    else:
        parts = [local, region]
    name = ", ".join(x for x in dict.fromkeys(parts) if x) or None
    cache[key] = name
    write_json(CACHE, cache)
    return name


def _nominatim(lat: float, lon: float) -> dict | None:
    global _last, _offline
    wait = 1.1 - (time.time() - _last)  # Nominatim policy: max 1 request/second
    if wait > 0:
        time.sleep(wait)
    _last = time.time()
    url = "https://nominatim.openstreetmap.org/reverse?" + urllib.parse.urlencode(
        {"lat": round(lat, 4), "lon": round(lon, 4), "format": "jsonv2", "zoom": 14, "accept-language": "en"})
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=10) as r:
            return json.loads(r.read().decode()).get("address", {})
    except Exception as e:
        _offline = True
        log(f"place lookup failed ({e}); use --location \"Place, Region\" to label manually")
        return None


_PARK_RANK = {"national_park": 0, "protected_area": 1, "nature_reserve": 2, "park": 3}


def _landmark(lat: float, lon: float) -> tuple[str | None, str | None]:
    """(famous spot near the camera, park or protected area the camera is in) from OpenStreetMap."""
    q = f"""[out:json][timeout:20];
is_in({lat},{lon})->.a;
(area.a["boundary"="national_park"]["name"];
 area.a["boundary"="protected_area"]["name"]["protect_class"~"^(1a|1b|2|3|5)$"];
 area.a["leisure"="nature_reserve"]["name"]["wikidata"];
 area.a["leisure"="park"]["name"]["wikidata"];)->.p;
.p out tags;
(nwr(around:700,{lat},{lon})["name"]["wikidata"]["tourism"~"^(attraction|viewpoint)$"];
 nwr(around:700,{lat},{lon})["name"]["wikidata"]["man_made"~"^(bridge|lighthouse|tower)$"];
 nwr(around:2500,{lat},{lon})["name"]["wikidata"]["natural"~"^(peak|arch|cliff|waterfall|rock|cape|glacier|volcano|beach|bay|spring|geyser)$"];
 nwr(around:700,{lat},{lon})["name"]["wikidata"]["waterway"="waterfall"];)->.s;
.s out tags center;"""
    try:
        req = urllib.request.Request(OVERPASS, data=urllib.parse.urlencode({"data": q}).encode(), headers=UA)
        with urllib.request.urlopen(req, timeout=25) as r:
            els = json.loads(r.read().decode()).get("elements", [])
    except Exception as e:
        log(f"landmark lookup skipped ({str(e)[:80]}); using the town name")
        return None, None
    park, park_rank = None, 99
    spots = []
    for el in els:
        t = el.get("tags") or {}
        name = t.get("name:en") or t.get("name")
        if not name:
            continue
        if el.get("type") == "area":
            kind = t.get("boundary") if t.get("boundary") in _PARK_RANK else t.get("leisure")
            rank = _PARK_RANK.get(kind, 9)
            if rank < park_rank:
                park, park_rank = name, rank
        else:
            c = el.get("center") or {"lat": el.get("lat"), "lon": el.get("lon")}
            if c.get("lat") is None:
                continue
            d = (float(c["lat"]) - lat) ** 2 + ((float(c["lon"]) - lon) * math.cos(math.radians(lat))) ** 2
            spots.append((d, name))
    spot = min(spots)[1] if spots else None
    return spot, park


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
