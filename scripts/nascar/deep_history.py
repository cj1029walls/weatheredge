#!/usr/bin/env python3
"""NASCAR deep history -> data/nascar/deep.json

Cup Series race results 2018-present from ESPN's public scoreboard API,
mapped to tracks and track types, plus race-day heat rebuilt from the
Open-Meteo archive so races can be tagged HOT (slick track) or not.

What this feeds (scripts/pro/nascar_build.py):
  * track history   — every driver's finishes at this week's track
  * track-type form — driver form on this track's TYPE, Next Gen era (2022+)
  * heat edge       — drivers who over/under-perform when the track runs hot

Points races only — Clash / All-Star / Duels are exhibition and excluded.
Heat lookups cached in data/nascar/wx_cache.json.

No third-party dependencies.
"""
import functools, json, os, re, sys, time, unicodedata, urllib.request
from datetime import datetime, timedelta

print = functools.partial(print, flush=True)

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
OUT = os.path.join(ROOT, "data", "nascar", "deep.json")
WX_CACHE = os.path.join(ROOT, "data", "nascar", "wx_cache.json")

SEASONS = list(range(2018, 2027))
SB_URL = "https://site.api.espn.com/apis/site/v2/sports/racing/nascar-premier/scoreboard?dates={y}"
ARC_URL = ("https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lon}"
           "&start_date={d}&end_date={d}&daily=temperature_2m_max"
           "&temperature_unit=fahrenheit&timezone={tz}")

EXHIBITION = re.compile(r"clash|all[- ]star|duel|qualif|exhibition|open\b", re.I)

# track keyword -> (key, type, lat, lon, tz)
# types: SS superspeedway · INT intermediate 1.5-2mi · SHORT short oval ·
#        FLAT flat 1-mile · ROAD road/street
TRACKS = [
    (r"daytona",              "daytona",     "SS",    29.185, -81.070, "America/New_York"),
    (r"talladega",            "talladega",   "SS",    33.566, -86.066, "America/Chicago"),
    (r"atlanta",              "atlanta",     "SS",    33.387, -84.316, "America/New_York"),
    (r"las vegas|south point|pennzoil", "vegas", "INT", 36.272, -115.010, "America/Los_Angeles"),
    (r"kansas",               "kansas",      "INT",   39.116, -94.831, "America/Chicago"),
    (r"charlotte|coca-cola 600|coke 600", "charlotte", "INT", 35.352, -80.683, "America/New_York"),
    (r"roval",                "roval",       "ROAD",  35.352, -80.683, "America/New_York"),
    (r"texas",                "texas",       "INT",   33.037, -97.282, "America/Chicago"),
    (r"homestead|miami",      "homestead",   "INT",   25.452, -80.409, "America/New_York"),
    (r"kentucky",             "kentucky",    "INT",   38.712, -84.916, "America/New_York"),
    (r"chicagoland",          "chicagoland", "INT",   41.475, -88.057, "America/Chicago"),
    (r"darlington|southern 500", "darlington", "INT", 34.295, -79.905, "America/New_York"),
    (r"dover",                "dover",       "INT",   39.190, -75.530, "America/New_York"),
    (r"michigan",             "michigan",    "INT",   42.065, -84.241, "America/Detroit"),
    (r"pocono",               "pocono",      "INT",   41.054, -75.512, "America/New_York"),
    (r"fontana|auto club",    "fontana",     "INT",   34.088, -117.500, "America/Los_Angeles"),
    (r"nashville",            "nashville",   "INT",   36.046, -86.408, "America/Chicago"),
    (r"gateway|wwt|world wide technology|illinois 300", "gateway", "FLAT", 38.651, -90.137, "America/Chicago"),
    (r"phoenix",              "phoenix",     "FLAT",  33.375, -112.311, "America/Phoenix"),
    (r"new hampshire|loudon|301", "loudon",  "FLAT",  43.363, -71.461, "America/New_York"),
    (r"iowa",                 "iowa",        "SHORT", 41.674, -93.014, "America/Chicago"),
    (r"richmond",             "richmond",    "SHORT", 37.592, -77.420, "America/New_York"),
    (r"bristol",              "bristol",     "SHORT", 36.516, -82.257, "America/New_York"),
    (r"martinsville",         "martinsville","SHORT", 36.634, -79.851, "America/New_York"),
    (r"north wilkesboro",     "wilkesboro",  "SHORT", 36.161, -81.065, "America/New_York"),
    (r"bowman gray",          "bowman-gray", "SHORT", 36.081, -80.222, "America/New_York"),
    (r"indianapolis|brickyard", "indy",      "INT",   39.795, -86.234, "America/Indiana/Indianapolis"),
    (r"sonoma",               "sonoma",      "ROAD",  38.161, -122.455, "America/Los_Angeles"),
    (r"watkins glen",         "glen",        "ROAD",  42.336, -76.927, "America/New_York"),
    (r"circuit of the americas|cota|austin", "cota", "ROAD", 30.133, -97.641, "America/Chicago"),
    (r"chicago street|grant park", "chicago-st", "ROAD", 41.876, -87.624, "America/Chicago"),
    (r"road america",         "road-america","ROAD",  43.798, -87.990, "America/Chicago"),
    (r"mexico",               "mexico-city", "ROAD",  19.406, -99.093, "America/Mexico_City"),
    (r"san diego|coronado",   "san-diego",   "ROAD",  32.678, -117.161, "America/Los_Angeles"),
]

HOT_F = 88          # race-day high ≥ this at the track -> HOT (slick) race


def get_json(url, tries=4):
    """ESPN blocks some datacenter IP ranges (403 from CI runners). Fallback
    chain: direct -> allorigins relay -> codetabs relay. Weekly cadence and a
    handful of calls, so relay load is trivial."""
    import urllib.parse
    variants = [
        url,
        "https://api.allorigins.win/raw?url=" + urllib.parse.quote(url, safe=""),
        "https://api.codetabs.com/v1/proxy?quest=" + urllib.parse.quote(url, safe=""),
    ]
    last = None
    for i in range(tries):
        for v in variants:
            try:
                req = urllib.request.Request(v, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "en-US,en;q=0.9",
                })
                with urllib.request.urlopen(req, timeout=60) as r:
                    return json.loads(r.read())
            except Exception as e:
                last = e
                continue
        if i < tries - 1:
            print(f"    retry {i+1}/{tries}: {last}")
            time.sleep(6 * (i + 1))
    raise last


def track_of(name):
    n = (name or "").lower()
    for rx, key, ttype, lat, lon, tz in TRACKS:
        if re.search(rx, n):
            return key, ttype, lat, lon, tz
    return None


def norm_driver(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).replace(" Jr.", "").replace(" Sr.", "").strip()


def day_high(lat, lon, tz, d, cache):
    ck = f"{round(lat,2)},{round(lon,2)}:{d}"
    if ck in cache:
        return cache[ck]
    try:
        j = get_json(ARC_URL.format(lat=lat, lon=lon, d=d,
                                    tz=tz.replace("/", "%2F")), tries=2)
        v = ((j.get("daily") or {}).get("temperature_2m_max") or [None])[0]
        cache[ck] = round(v) if v is not None else None
        time.sleep(0.5)
        return cache[ck]
    except Exception as e:
        print(f"    wx skip {d}: {e}")
        cache[ck] = None
        return None


def main():
    cache = {}
    if os.path.exists(WX_CACHE):
        try:
            cache = json.load(open(WX_CACHE))
        except Exception:
            cache = {}

    tracks_meta = {key: dict(type=t) for _, key, t, _, _, _ in TRACKS}
    drivers, races = {}, []
    for y in SEASONS:
        try:
            sb = get_json(SB_URL.format(y=y))
        except Exception as e:
            print(f"season {y}: unavailable ({e})")
            continue
        evs = sb.get("events") or []
        n_pts = 0
        for ev in evs:
            name = ev.get("name") or ""
            if EXHIBITION.search(name):
                continue
            tk = track_of(name)
            if not tk:
                print(f"    unmapped: {name}")
                continue
            key, ttype, lat, lon, tz = tk
            comps = ev.get("competitions") or []
            if not comps:
                continue
            rows = comps[0].get("competitors") or []
            if len(rows) < 20:
                continue
            done = ((ev.get("status") or {}).get("type") or {}).get("completed")
            if done is False:
                continue
            date = (ev.get("date") or "")[:10]
            hi = day_high(lat, lon, tz, date, cache) if date else None
            hot = 1 if (hi is not None and hi >= HOT_F) else 0
            n = len(rows)
            races.append(dict(y=y, d=date, track=key, type=ttype, n=n,
                              hi=hi, hot=bool(hot)))
            n_pts += 1
            for i, c in enumerate(rows):
                ath = (c.get("athlete") or {}).get("displayName")
                if not ath:
                    continue
                pos = c.get("order") or (i + 1)
                drivers.setdefault(norm_driver(ath), []).append(
                    [key, y, int(pos), n, hot])
        print(f"season {y}: {n_pts} points races mapped")

    drivers = {p: sorted(rows, key=lambda r: r[1])
               for p, rows in drivers.items() if len(rows) >= 8}

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(dict(built=datetime.utcnow().strftime("%Y-%m-%d"),
                   seasons=[SEASONS[0], SEASONS[-1]], hotF=HOT_F,
                   tracks=tracks_meta, races=races, drivers=drivers),
              open(OUT, "w"))
    json.dump(cache, open(WX_CACHE, "w"))
    kb = os.path.getsize(OUT) // 1024
    print(f"wrote {OUT}: {len(races)} races · {len(drivers)} drivers · {kb} KB")


if __name__ == "__main__":
    main()
