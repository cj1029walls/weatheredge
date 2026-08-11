#!/usr/bin/env python3
"""PGA deep history -> data/pga/deep.json

Player results for every PGA Tour event 2018-present from ESPN's public
scoreboard API, plus event-week weather rebuilt from the Open-Meteo archive
so editions can be tagged WINDY or CALM.

What this feeds (scripts/pro/pga_build.py):
  * course history — every player's past finishes at this week's event
  * wind pedigree  — how a player's finishes hold up in windy editions
  * recent form    — last-5-start trend

Positions are ESPN's final leaderboard order (1 = winner). We express every
finish as a FIELD PERCENTILE (pos / field size) so a 20th at a 156-man open
isn't scored like 20th of 30 at the TOUR Championship.

Weather tagging only where an event has a stable host course (EVENT_COORDS)
— rotating-venue events (BMW etc.) are excluded from wind tagging but still
count for course history and form. Archive lookups are cached in
data/pga/wx_cache.json so weekly runs only fetch new editions.

No third-party dependencies.
"""
import functools, json, os, re, sys, time, unicodedata, urllib.request
from datetime import datetime

print = functools.partial(print, flush=True)

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
OUT = os.path.join(ROOT, "data", "pga", "deep.json")
WX_CACHE = os.path.join(ROOT, "data", "pga", "wx_cache.json")

SEASONS = list(range(2018, 2027))
SB_URL = "https://site.api.espn.com/apis/site/v2/sports/golf/pga/scoreboard?dates={y}"
ARC_URL = ("https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lon}"
           "&start_date={d0}&end_date={d1}&hourly=wind_speed_10m,wind_gusts_10m"
           "&wind_speed_unit=mph&timezone={tz}")

# canonical event keys: regex on the (lowercased) ESPN event name.
# Sponsor names churn — the regexes anchor on the stable part.
CANON = [
    (r"sentry|tournament of champions", "sentry"),
    (r"st\.? jude", "st-jude"),
    (r"bmw championship", "bmw"),
    (r"tour championship", "tour-champ"),
    (r"wyndham", "wyndham"),
    (r"bermuda", "bermuda"),
    (r"mexico open|vidanta", "mexico-open"),
    (r"world wide technology|wwt championship", "wwt"),
    (r"\brsm\b", "rsm"),
    (r"black desert|bank of utah", "black-desert"),
    (r"zozo|baycurrent", "japan"),
    (r"sony open", "sony"),
    (r"american express|amex|desert classic|careerbuilder", "amex"),
    (r"farmers insurance|torrey", "torrey"),
    (r"phoenix open|waste management", "phoenix"),
    (r"pebble beach|at&t pro-am", "pebble"),
    (r"genesis invitational|riviera", "riviera"),
    (r"cognizant|honda classic", "honda"),
    (r"arnold palmer|bay hill", "bay-hill"),
    (r"players championship", "players"),
    (r"valspar", "valspar"),
    (r"texas open|valero", "valero"),
    (r"masters", "masters"),
    (r"heritage|rbc heritage|harbour town", "harbour-town"),
    (r"zurich classic", "zurich"),
    (r"byron nelson", "byron-nelson"),
    (r"pga championship", "pga-champ"),
    (r"colonial|charles schwab|crowne plaza", "colonial"),
    (r"memorial", "memorial"),
    (r"canadian open", "canadian"),
    (r"u\.?s\.? open", "us-open"),
    (r"travelers", "travelers"),
    (r"rocket mortgage|rocket classic", "detroit"),
    (r"john deere", "john-deere"),
    (r"scottish open", "scottish"),
    (r"open championship|british open", "the-open"),
    (r"3m open", "3m"),
    (r"barracuda", "barracuda"),
    (r"houston open", "houston"),
    (r"sanderson", "sanderson"),
    (r"shriners", "shriners"),
    (r"barbasol", "barbasol"),
    (r"greenbrier|military tribute", "greenbrier"),
    (r"puerto rico", "puerto-rico"),
    (r"corales|punta cana", "corales"),
    (r"olympic|olympics", "olympics"),
    (r"presidents cup|ryder cup", "team-cup"),
]

# stable-course coordinates for wind tagging (lat, lon, tz)
EVENT_COORDS = {
    "sentry": (20.999, -156.665, "Pacific/Honolulu"),        # Kapalua
    "st-jude": (35.062, -89.853, "America/Chicago"),         # TPC Southwind
    "tour-champ": (33.740, -84.308, "America/New_York"),     # East Lake
    "wyndham": (36.048, -79.888, "America/New_York"),        # Sedgefield
    "bermuda": (32.253, -64.863, "Atlantic/Bermuda"),        # Port Royal
    "sony": (21.274, -157.777, "Pacific/Honolulu"),          # Waialae
    "torrey": (32.905, -117.245, "America/Los_Angeles"),
    "phoenix": (33.640, -111.911, "America/Phoenix"),        # TPC Scottsdale
    "pebble": (36.567, -121.950, "America/Los_Angeles"),
    "riviera": (34.048, -118.501, "America/Los_Angeles"),
    "honda": (26.823, -80.140, "America/New_York"),          # PGA National
    "bay-hill": (28.462, -81.507, "America/New_York"),
    "players": (30.198, -81.394, "America/New_York"),        # TPC Sawgrass
    "valspar": (28.089, -82.756, "America/New_York"),        # Innisbrook
    "valero": (29.681, -98.629, "America/Chicago"),          # TPC San Antonio
    "masters": (33.503, -82.020, "America/New_York"),        # Augusta
    "harbour-town": (32.139, -80.803, "America/New_York"),
    "byron-nelson": (33.088, -96.960, "America/Chicago"),    # TPC Craig Ranch
    "colonial": (32.709, -97.362, "America/Chicago"),
    "memorial": (40.156, -83.121, "America/New_York"),       # Muirfield Village
    "travelers": (41.723, -72.660, "America/New_York"),      # TPC River Highlands
    "detroit": (42.421, -83.084, "America/Detroit"),
    "john-deere": (41.446, -90.396, "America/Chicago"),
    "3m": (45.244, -93.010, "America/Chicago"),              # TPC Twin Cities
    "houston": (30.056, -95.484, "America/Chicago"),         # Memorial Park approx
    "sanderson": (32.437, -90.129, "America/Chicago"),
    "shriners": (36.079, -115.283, "America/Los_Angeles"),   # TPC Summerlin
    "puerto-rico": (18.397, -65.836, "America/Puerto_Rico"),
    "corales": (18.516, -68.363, "America/Santo_Domingo"),
    "mexico-open": (20.691, -105.294, "America/Bahia_Banderas"),
    "wwt": (22.903, -110.021, "America/Mazatlan"),
    "amex": (33.672, -116.240, "America/Los_Angeles"),       # La Quinta
    "canadian": None, "us-open": None, "the-open": None, "pga-champ": None,
    "bmw": None, "scottish": None, "japan": None, "zurich": None,
    "greenbrier": (37.786, -80.308, "America/New_York"),
    "rsm": (31.155, -81.386, "America/New_York"),            # Sea Island
    "black-desert": (37.168, -113.679, "America/Denver"),
}

WINDY_MPH = 12       # avg daytime wind over the event ≥ this -> WINDY edition


def get_json(url, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "dfsradar-build/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except Exception as e:
            if i == tries - 1:
                raise
            print(f"    retry {i+1}/{tries}: {e}")
            time.sleep(6 * (i + 1))


def canon_key(name):
    n = (name or "").lower()
    for rx, key in CANON:
        if re.search(rx, n):
            return key
    return re.sub(r"[^a-z0-9]+", "-", n).strip("-")[:40] or None


def norm_player(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip()


def event_wind(key, d0, d1, cache):
    ck = f"{key}:{d0}"
    if ck in cache:
        return cache[ck]
    co = EVENT_COORDS.get(key)
    if not co:
        cache[ck] = None
        return None
    lat, lon, tz = co
    try:
        j = get_json(ARC_URL.format(lat=lat, lon=lon, d0=d0, d1=d1,
                                    tz=tz.replace("/", "%2F")), tries=2)
        hrs = j.get("hourly") or {}
        winds = []
        for t, w in zip(hrs.get("time") or [], hrs.get("wind_speed_10m") or []):
            hh = int(t[11:13])
            if w is not None and 7 <= hh <= 18:
                winds.append(w)
        out = round(sum(winds) / len(winds), 1) if winds else None
        cache[ck] = out
        time.sleep(0.6)
        return out
    except Exception as e:
        print(f"    wx skip {key} {d0}: {e}")
        cache[ck] = None
        return None


def main():
    cache = {}
    if os.path.exists(WX_CACHE):
        try:
            cache = json.load(open(WX_CACHE))
        except Exception:
            cache = {}

    events, players = {}, {}
    for y in SEASONS:
        try:
            sb = get_json(SB_URL.format(y=y))
        except Exception as e:
            print(f"season {y}: unavailable ({e})")
            continue
        evs = sb.get("events") or []
        print(f"season {y}: {len(evs)} events")
        for ev in evs:
            name = ev.get("name") or ""
            key = canon_key(name)
            if not key or key == "team-cup":
                continue
            comps = (ev.get("competitions") or [])
            if not comps:
                continue
            rows = comps[0].get("competitors") or []
            if len(rows) < 20:            # skip TGL/exhibitions/tiny fields
                continue
            date = (ev.get("date") or "")[:10]
            if not date:
                continue
            # already finished only (skip in-progress current event)
            status = ((ev.get("status") or {}).get("type") or {}).get("completed")
            if status is False:
                continue
            n = len(rows)
            e = events.setdefault(key, dict(names=set(), editions={}))
            e["names"].add(name)
            wind = event_wind(key, date, _plus3(date), cache)
            e["editions"][str(y)] = dict(d=date, n=n, wind=wind,
                                         windy=(wind is not None and wind >= WINDY_MPH))
            for i, c in enumerate(rows):
                ath = (c.get("athlete") or {}).get("displayName")
                if not ath:
                    continue
                pos = c.get("order") or (i + 1)
                players.setdefault(norm_player(ath), []).append(
                    [key, y, int(pos), n])

    # trim: players with fewer than 5 career starts add noise and bytes
    players = {p: sorted(rows, key=lambda r: (r[1],))
               for p, rows in players.items() if len(rows) >= 5}
    for e in events.values():
        e["names"] = sorted(e["names"])

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(dict(built=datetime.utcnow().strftime("%Y-%m-%d"),
                   seasons=[SEASONS[0], SEASONS[-1]],
                   windyMph=WINDY_MPH, events=events, players=players),
              open(OUT, "w"))
    json.dump(cache, open(WX_CACHE, "w"))
    kb = os.path.getsize(OUT) // 1024
    tagged = sum(1 for e in events.values()
                 for ed in e["editions"].values() if ed["wind"] is not None)
    print(f"wrote {OUT}: {len(events)} events · {len(players)} players · "
          f"{tagged} weather-tagged editions · {kb} KB")


def _plus3(d):
    from datetime import timedelta
    return (datetime.strptime(d, "%Y-%m-%d") + timedelta(days=3)).strftime("%Y-%m-%d")


if __name__ == "__main__":
    main()
