#!/usr/bin/env python3
"""Daily build: today's real MLB slate + first-pitch forecasts + similar-weather
history stats -> site/data.json (consumed by site/index.html).

Usage:
  python scripts/daily_build.py                 # today (US/Eastern)
  python scripts/daily_build.py --date 2026-07-30
  python scripts/daily_build.py --offline       # use tests/fixtures (no network)

Optional data/lines.json lets you pin real betting totals:
  { "WSH@CHC": 9.0, "NYY@BOS": 9.5 }
Games without a pinned line use the median total of their matched sample
(marked lineSource="est").

No third-party dependencies.
"""
import argparse, functools, json, os, statistics, sys, time, urllib.error, urllib.request
from datetime import datetime, timezone, timedelta

print = functools.partial(print, flush=True)
sys.path.insert(0, os.path.dirname(__file__))
from parks import PARKS, MLBID_TO_CODE, wind_rel_angle, wind_sector, wind_label

ROOT = os.path.join(os.path.dirname(__file__), "..")
HISTORY = os.path.join(ROOT, "data", "parks_history.json")
LINES = os.path.join(ROOT, "data", "lines.json")
OUT = os.path.join(ROOT, "site", "data.json")
FIXTURES = os.path.join(ROOT, "tests", "fixtures")

SCHED_URL = "https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={date}"
FC_URL = ("https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
          "&hourly=temperature_2m,dew_point_2m,wind_speed_10m,wind_direction_10m,"
          "cloud_cover,precipitation_probability"
          "&temperature_unit=fahrenheit&wind_speed_unit=mph&timezone={tz}&forecast_days=3")

ET = timezone(timedelta(hours=-4))  # ET (DST); slate dates only, precision not critical

# ---- The Odds API (free tier) — real consensus totals ----
ODDS_URL = ("https://api.the-odds-api.com/v4/sports/baseball_mlb/odds"
            "?apiKey={key}&regions=us&markets=totals&oddsFormat=american")
ODDS_TEAM_NAMES = {
    "Arizona Diamondbacks":"ARI", "Athletics":"ATH", "Oakland Athletics":"ATH",
    "Atlanta Braves":"ATL", "Baltimore Orioles":"BAL", "Boston Red Sox":"BOS",
    "Chicago Cubs":"CHC", "Cincinnati Reds":"CIN", "Cleveland Guardians":"CLE",
    "Colorado Rockies":"COL", "Chicago White Sox":"CWS", "Detroit Tigers":"DET",
    "Houston Astros":"HOU", "Kansas City Royals":"KC", "Los Angeles Angels":"LAA",
    "Los Angeles Dodgers":"LAD", "Miami Marlins":"MIA", "Milwaukee Brewers":"MIL",
    "Minnesota Twins":"MIN", "New York Mets":"NYM", "New York Yankees":"NYY",
    "Philadelphia Phillies":"PHI", "Pittsburgh Pirates":"PIT", "San Diego Padres":"SD",
    "Seattle Mariners":"SEA", "San Francisco Giants":"SF", "St. Louis Cardinals":"STL",
    "Tampa Bay Rays":"TB", "Texas Rangers":"TEX", "Toronto Blue Jays":"TOR",
    "Washington Nationals":"WSH",
}

def fetch_book_lines():
    """One call → {"AWAY@HOME": consensus total}. Median across all US books.
    Free tier budget: 3 runs/day ≈ 93 calls/month of the 500 allowed.
    Missing key or any failure → {} (build falls back to sample-median estimates)."""
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        print("odds api: no ODDS_API_KEY set — using estimated totals")
        return {}
    try:
        events = get_json(ODDS_URL.format(key=key), tries=3)
    except Exception as e:
        print(f"odds api unavailable ({e}) — using estimated totals")
        return {}
    out = {}
    for ev in events:
        away = ODDS_TEAM_NAMES.get(ev.get("away_team"))
        home = ODDS_TEAM_NAMES.get(ev.get("home_team"))
        if not away or not home:
            continue
        points = []
        for bk in ev.get("bookmakers", []):
            for mk in bk.get("markets", []):
                if mk.get("key") == "totals":
                    for oc in mk.get("outcomes", []):
                        if oc.get("name") == "Over" and oc.get("point") is not None:
                            points.append(oc["point"])
        if points:
            out[f"{away}@{home}"] = statistics.median(points)
    print(f"odds api: real totals for {len(out)} games")
    return out

def get_json(url, tries=5):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "weatheredge-build/1.0"})
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read())
        except Exception as e:
            if i == tries - 1:
                raise
            wait = 45 if (isinstance(e, urllib.error.HTTPError) and e.code == 429) else 8 * (i + 1)
            print(f"    retry {i+1}/{tries} in {wait}s: {e}")
            time.sleep(wait)

_FC_CACHE = {}
def get_forecast(meta):
    key = meta["name"]
    if key not in _FC_CACHE:
        _FC_CACHE[key] = get_json(FC_URL.format(lat=meta["lat"], lon=meta["lon"],
                                                tz=meta["tz"].replace("/", "%2F")))
        time.sleep(1)
    return _FC_CACHE[key]

def sky_of(cloud, precip_prob, hour_local):
    night = hour_local >= 20 or hour_local < 6
    if precip_prob is not None and precip_prob >= 55: return ("🌧️", "Rain risk")
    if cloud is None: return ("🌤️", "—")
    if cloud >= 85: return ("☁️", "Overcast")
    if cloud >= 45: return ("🌙", "Partly cloudy") if night else ("⛅", "Partly cloudy")
    return ("🌙", "Clear") if night else ("☀️", "Sunny")

def roof_closed(meta, temp, precip_prob):
    if meta["roof"] == "dome": return True
    if meta["roof"] == "retract":
        return temp >= 95 or temp <= 48 or (precip_prob or 0) >= 45
    return False

def match_games(hist, temp, wind, rel, dome):
    """Adaptive similar-conditions matching. Returns (rows, note)."""
    games = hist["games"]
    if dome:
        return games, "all games at this park (roof closed → weather-neutral)"
    sect = wind_sector(rel)
    for dt, dw, use_sector in ((6, 6, True), (8, 8, True), (10, 10, True), (12, 99, False)):
        rows = [g for g in games
                if abs(g["t"] - temp) <= dt
                and abs(g["w"] - wind) <= dw
                and (not use_sector or wind_sector(g["rel"]) == sect)]
        if len(rows) >= 12:
            note = f"±{dt}° temp, ±{dw} mph, wind {sect}" if use_sector else f"±{dt}° temp (widened)"
            return rows, note
    return rows, "small sample — widest window"

def pct_delta(a, b):
    if not b: return 0
    return round((a - b) / b * 100)

def build_game(g, hist_all, league, lines, offline):
    home_id = g["teams"]["home"]["team"]["id"]
    away_id = g["teams"]["away"]["team"]["id"]
    home = MLBID_TO_CODE.get(home_id)
    away = MLBID_TO_CODE.get(away_id)
    if not home or not away:
        return None
    meta = PARKS[home]
    # first pitch in park-local time
    utc = datetime.fromisoformat(g["gameDate"].replace("Z", "+00:00"))
    et = utc.astimezone(ET)
    time_str = et.strftime("%-I:%M %p ET")
    sort_time = et.hour * 100 + et.minute

    # forecast
    if offline:
        fc = json.load(open(os.path.join(FIXTURES, f"forecast_{home}.json")))
    else:
        fc = get_forecast(meta)
    h = fc["hourly"]
    # find the hourly index at the park-local first-pitch hour
    import zoneinfo
    park_tz = zoneinfo.ZoneInfo(meta["tz"])
    fp_park = utc.astimezone(park_tz)
    want = fp_park.strftime("%Y-%m-%dT%H")
    idx = next((i for i, t in enumerate(h["time"]) if t.startswith(want)), None)
    if idx is None:
        idx = min(range(len(h["time"])), key=lambda i: abs(
            datetime.fromisoformat(h["time"][i]).replace(tzinfo=park_tz).timestamp() - fp_park.timestamp()))
    temp = round(h["temperature_2m"][idx])
    dew = round(h["dew_point_2m"][idx])
    wind = round(h["wind_speed_10m"][idx])
    wdir = h["wind_direction_10m"][idx]
    cloud = h.get("cloud_cover", [None]*len(h["time"]))[idx]
    pprob = h.get("precipitation_probability", [None]*len(h["time"]))[idx]

    rel = wind_rel_angle(wdir, meta["bearing"])
    dome = roof_closed(meta, temp, pprob)
    icon, sky = sky_of(cloud, pprob, fp_park.hour)
    if dome:
        icon, sky = "🏟️", "Indoor"

    hist = hist_all.get(home)
    game_id = f"{away.lower()}-{home.lower()}-{g.get('gamePk', 0) % 1000}"
    out = dict(id=game_id, away=away, home=home,
               park=meta["name"] + ("" if meta["roof"] == "open" else
                                    " · roof closed" if dome else " · roof open"),
               time=time_str, sortTime=sort_time,
               temp=temp, wind=0 if dome else wind, dir="—" if dome else deg_to_compass(wdir),
               windAngle=round(rel), windLabel="ROOF CLOSED" if dome else wind_label(rel),
               dew=dew, sky=sky, skyIcon=icon, dome=dome)

    if not hist or not hist["avg"]["n"]:
        out.update(sample=0, hr=0, runs=0, ks=0, hrGm=0, hrPark=0,
                   mlb=dict(hr=0, runs=0, ks=0), ou=dict(under=0, push=0, over=0),
                   total=0, matches=[], note="history not built yet")
        return out

    rows, note = match_games(hist, temp, wind, rel, dome)
    n = len(rows)
    m_hr = statistics.mean(x["hr"] for x in rows) if rows else 0
    m_r = statistics.mean(x["r"] for x in rows) if rows else 0
    m_so = statistics.mean(x["so"] for x in rows) if rows else 0
    avg = hist["avg"]

    line = lines.get(f"{away}@{home}")
    line_source = "book" if line is not None else "est"
    if line is None and rows:
        # estimate: the half-point line that best balances the matched sample
        med = int(statistics.median(x["r"] for x in rows))
        candidates = [k + 0.5 for k in range(max(4, med - 3), med + 4)]
        def imbalance(L):
            o = sum(1 for x in rows if x["r"] > L); u = sum(1 for x in rows if x["r"] < L)
            return abs(o - u)
        line = min(candidates, key=imbalance)
    over = sum(1 for x in rows if x["r"] > line)
    under = sum(1 for x in rows if x["r"] < line)
    push = n - over - under

    out.update(
        sample=n,
        hr=pct_delta(m_hr, avg["hr"]), runs=pct_delta(m_r, avg["r"]), ks=pct_delta(m_so, avg["so"]),
        hrGm=round(m_hr, 1), hrPark=avg["hr"],
        mlb=dict(hr=pct_delta(m_hr, league["hr"]), runs=pct_delta(m_r, league["r"]),
                 ks=pct_delta(m_so, league["so"])),
        ou=dict(over=round(over / n * 100) if n else 0,
                under=round(under / n * 100) if n else 0,
                push=max(0, 100 - (round(over / n * 100) + round(under / n * 100))) if n else 0),
        total=line or 0, lineSource=line_source, note=note,
        matches=[dict(d=x["d"], t=x["t"], w=x["w"], r=x["r"], hr=x["hr"])
                 for x in sorted(rows, key=lambda x: x["d"], reverse=True)[:15]],
    )
    if dome:
        out["hr"] = out["runs"] = out["ks"] = 0
    return out

def deg_to_compass(deg):
    dirs = ["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSW","SW","WSW","W","WNW","NW","NNW"]
    return dirs[round(deg / 22.5) % 16]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()
    date_str = args.date or datetime.now(ET).strftime("%Y-%m-%d")

    hist_path = HISTORY
    if not os.path.exists(hist_path):
        if args.offline:
            hist_path = os.path.join(FIXTURES, "parks_history_fixture.json")
        else:
            sys.exit("data/parks_history.json missing — run the 'Build history' workflow first.")
    hist_all = json.load(open(hist_path))
    league = hist_all["_league"]
    lines = {} if args.offline else fetch_book_lines()
    if os.path.exists(LINES):
        lines.update(json.load(open(LINES)))   # manual pins always win

    if args.offline:
        sched = json.load(open(os.path.join(FIXTURES, "schedule.json")))
    else:
        sched = get_json(SCHED_URL.format(date=date_str))

    games = []
    for day in sched.get("dates", []):
        for g in day.get("games", []):
            try:
                built = build_game(g, hist_all, league, lines, args.offline)
                if built: games.append(built)
            except Exception as e:
                print(f"  skip {g.get('gamePk')}: {e}")

    scheduled = sum(len(day.get("games", [])) for day in sched.get("dates", []))
    if scheduled and not games:
        sys.exit(f"All {scheduled} scheduled games failed to build — refusing to publish an empty slate.")

    label = datetime.strptime(date_str, "%Y-%m-%d").strftime("%A, %B %-d")
    payload = dict(generated=datetime.now(ET).strftime("%Y-%m-%d %H:%M ET"),
                   date=date_str, dateLabel=label,
                   league=league, seasons=hist_all.get("_seasons", []),
                   games=sorted(games, key=lambda x: x["sortTime"]))
    with open(OUT, "w") as f:
        json.dump(payload, f, separators=(",", ":"))
    print(f"Wrote {OUT}: {len(games)} games for {date_str}")

if __name__ == "__main__":
    main()
