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
HITTERS = os.path.join(ROOT, "data", "hitters_history.json")
LINES = os.path.join(ROOT, "data", "lines.json")
OUT = os.path.join(ROOT, "site", "data.json")
FIXTURES = os.path.join(ROOT, "tests", "fixtures")

SCHED_URL = "https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={date}"
SCHED_PP_URL = SCHED_URL + "&hydrate=probablePitcher,officials"
BOX_URL = "https://statsapi.mlb.com/api/v1/game/{pk}/boxscore"
GAMELOG_URL = ("https://statsapi.mlb.com/api/v1/people/{pid}/stats"
               "?stats=gameLog&group=pitching&season={season}")
PREDS_DIR = os.path.join(ROOT, "data", "predictions")
ACCURACY = os.path.join(ROOT, "data", "accuracy.json")
SITE_ACCURACY = os.path.join(ROOT, "site", "accuracy.json")
FC_URL = ("https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
          "&hourly=temperature_2m,dew_point_2m,wind_speed_10m,wind_direction_10m,"
          "cloud_cover,precipitation_probability,relative_humidity_2m,surface_pressure"
          "&temperature_unit=fahrenheit&wind_speed_unit=mph&timezone={tz}&forecast_days=3")
UMPS = os.path.join(ROOT, "data", "umps_history.json")

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

WET_IN = 0.05   # inches over the ~3h game window = "wet game"

# ---- plate umpire: his games vs league, from Retrosheet history ----
def ump_card(g_sched, umps_all):
    officials = g_sched.get("officials") or []
    plate = next((o for o in officials
                  if o.get("officialType") == "Home Plate" and o.get("official")), None)
    if not plate:
        return None
    name = plate["official"].get("fullName")
    if not name:
        return None
    out = dict(name=name)
    if umps_all and name in umps_all:
        u, lg = umps_all[name], umps_all["_league"]
        out.update(n=u["n"], r=u["r"], hr=u["hr"], so=u["so"],
                   dR=pct_delta(u["r"], lg["r"]),
                   dHr=pct_delta(u["hr"], lg["hr"]),
                   dSo=pct_delta(u["so"], lg["so"]))
    return out

# ---- wind receptivity: how much outward wind moves HR at this park ----
def wind_receptivity(hist):
    """Regress HR on the outward wind component across the park's history.
    Returns (rating, pct10) — pct10 = HR change per 10 mph of outward wind."""
    import math
    games = [g for g in hist["games"] if g.get("w") is not None]
    if len(games) < 200:
        return None
    xs = [g["w"] * math.cos(math.radians(g["rel"])) for g in games]
    ys = [g["hr"] for g in games]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if not sxx or not my:
        return None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    pct10 = round(slope * 10 / my * 100)
    a = abs(pct10)
    rating = "LOW" if a < 5 else "MEDIUM" if a < 12 else "HIGH" if a < 25 else "EXTREME"
    return dict(rating=rating, pct10=pct10)

# ---- conditions MVP: each team's hottest bat in this weather ----
def conditions_mvp(team, temp, wind, hitters_all):
    """Best slugger in similar weather (±8° / ±8 mph, min 25 AB)."""
    if not hitters_all:
        return None
    tm = hitters_all.get(team)
    if not tm:
        return None
    best = None
    for p in tm["players"].values():
        sim = [r for r in p["g"] if abs(r[0] - temp) <= 8 and abs(r[1] - wind) <= 8]
        ab = sum(r[2] for r in sim)
        if ab < 25:
            continue
        slg = sum(r[3] for r in sim) / ab
        all_ab = sum(r[2] for r in p["g"])
        cand = dict(name=p["name"], slg=round(slg, 3),
                    hr=sum(r[4] for r in sim), ab=ab, games=len(sim),
                    allSlg=round(sum(r[3] for r in p["g"]) / all_ab, 3) if all_ab else 0)
        if best is None or slg > best["slg"]:
            best = cand
    return best

# ---- probable pitchers: real starts in similar conditions ----
_PITCH_CACHE = {}

def _ip_to_float(ip):
    try:
        whole, _, frac = str(ip).partition(".")
        return int(whole) + int(frac or 0) / 3.0
    except (ValueError, TypeError):
        return 0.0

def _pitcher_starts(pid, seasons):
    """[(d, park_code, ip, so, hr, er), ...] from statsapi game logs."""
    if pid in _PITCH_CACHE:
        return _PITCH_CACHE[pid]
    starts = []
    for season in seasons:
        try:
            data = get_json(GAMELOG_URL.format(pid=pid, season=season), tries=2)
        except Exception as e:
            print(f"    pitcher {pid} {season}: {e}")
            continue
        for s in (data.get("stats") or [{}])[0].get("splits", []):
            st = s.get("stat", {})
            ip = _ip_to_float(st.get("inningsPitched", 0))
            if ip <= 0:
                continue
            home_id = (s.get("team") if s.get("isHome") else s.get("opponent") or {}).get("id")
            code = MLBID_TO_CODE.get(home_id)
            d = (s.get("date") or "").replace("-", "")
            if not code or len(d) != 8:
                continue
            starts.append((d, code, ip, st.get("strikeOuts", 0) or 0,
                           st.get("homeRuns", 0) or 0, st.get("earnedRuns", 0) or 0))
        time.sleep(0.3)
    _PITCH_CACHE[pid] = starts
    return starts

def _per9(rows):
    ip = sum(r[2] for r in rows)
    if ip <= 0:
        return None
    return dict(n=len(rows), ip=round(ip, 1),
                k9=round(sum(r[3] for r in rows) / ip * 9, 1),
                hr9=round(sum(r[4] for r in rows) / ip * 9, 2),
                era=round(sum(r[5] for r in rows) / ip * 9, 2))

def pitcher_conditions(pp, hist_all, temp, wind, dome, seasons):
    """One probable pitcher's real starts in similar weather vs overall."""
    if not pp or not pp.get("id"):
        return None
    starts = _pitcher_starts(pp["id"], seasons)
    if not starts:
        return None
    # join each start to that park's historical first-pitch weather
    wx_starts = []
    for d, code, ip, so, hr, er in starts:
        hist = hist_all.get(code)
        if not hist:
            continue
        g = next((x for x in hist["games"] if x["d"] == d), None)
        if g:
            wx_starts.append((g["t"], g["w"], ip, so, hr, er))
    overall = _per9([(0, 0, ip, so, hr, er) for d, c, ip, so, hr, er in starts])
    if dome:
        return dict(id=pp.get("id"), name=pp.get("fullName", "TBD"), sim=None, all=overall,
                    note="roof closed — weather-neutral")
    sim_rows = [(t, w, ip, so, hr, er) for t, w, ip, so, hr, er in wx_starts
                if abs(t - temp) <= 8 and abs(w - wind) <= 8]
    note = "±8° temp, ±8 mph wind"
    if len(sim_rows) < 5:
        sim_rows = [(t, w, ip, so, hr, er) for t, w, ip, so, hr, er in wx_starts
                    if abs(t - temp) <= 10]
        note = "±10° temp (widened)"
    sim = _per9(sim_rows) if len(sim_rows) >= 3 else None
    return dict(id=pp.get("id"), name=pp.get("fullName", "TBD"), sim=sim, all=overall, note=note)

def wet_split(hist, line):
    """Park-wide wet vs dry splits (needs history built with precip data)."""
    games = [g for g in hist["games"] if "p" in g]
    if not games:
        return None
    wet = [g for g in games if g["p"] >= WET_IN]
    dry = [g for g in games if g["p"] < WET_IN]
    if len(wet) < 5 or not dry:
        return None
    def s(rows):
        return dict(n=len(rows),
                    r=round(statistics.mean(x["r"] for x in rows), 2),
                    hr=round(statistics.mean(x["hr"] for x in rows), 2),
                    so=round(statistics.mean(x["so"] for x in rows), 2))
    out = dict(wet=s(wet), dry=s(dry))
    if line:
        n = len(wet)
        out["wetOver"] = round(sum(1 for x in wet if era_runs(x) > line) / n * 100)
        out["wetUnder"] = round(sum(1 for x in wet if era_runs(x) < line) / n * 100)
    return out

ERA_FACTOR = {}   # season -> run-environment scale (filled in main)

def build_era_factors(hist_all):
    """Scale each historical season's runs to the recent run environment.

    2019's juiced ball ran ~0.5 r/g hotter than recent seasons; matching raw
    totals against today's line over-calls overs. Reference = mean of the two
    most recent completed seasons in the dataset.
    """
    by_year = {}
    for code, h in hist_all.items():
        if code.startswith("_"):
            continue
        for x in h.get("games", []):
            y = int(str(x["d"])[:4])
            by_year.setdefault(y, []).append(x["r"])
    if not by_year:
        return
    season_avg = {y: statistics.mean(v) for y, v in by_year.items() if len(v) >= 100}
    ref_years = sorted(season_avg)[-2:]
    ref = statistics.mean(season_avg[y] for y in ref_years)
    for y, avg in season_avg.items():
        ERA_FACTOR[y] = ref / avg
    spread = {y: round(f, 3) for y, f in sorted(ERA_FACTOR.items())}
    print(f"era factors (ref {ref:.2f} r/g): {spread}")

def era_runs(x):
    """A matched game's total runs, scaled to the current run environment."""
    return x["r"] * ERA_FACTOR.get(int(str(x["d"])[:4]), 1.0)

def build_game(g, hist_all, league, lines, offline, hitters_all=None, umps_all=None):
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

    # hour-by-hour through the game window (first pitch + 3h)
    hourly = []
    if not dome:
        pp_arr = h.get("precipitation_probability", [None] * len(h["time"]))
        rh_arr = h.get("relative_humidity_2m", [None] * len(h["time"]))
        cl_arr = h.get("cloud_cover", [None] * len(h["time"]))
        for off in range(-1, 4):          # one hour pre-game through +3h
            j = idx + off
            if j < 0 or j >= len(h["time"]):
                continue
            wd_j = h["wind_direction_10m"][j]
            pj, rj = pp_arr[j], rh_arr[j]
            hh = datetime.fromisoformat(h["time"][j])
            icon_j, _ = sky_of(cl_arr[j], pj, hh.hour)
            hourly.append(dict(
                lab=hh.strftime("%-I %p"), fp=(off == 0), c=icon_j,
                t=round(h["temperature_2m"][j]),
                dew=round(h["dew_point_2m"][j]),
                w=round(h["wind_speed_10m"][j]),
                dir=deg_to_compass(wd_j),
                rel=round(wind_rel_angle(wd_j, meta["bearing"])),
                rain=None if pj is None else round(pj),
                rh=None if rj is None else round(rj)))
    rh0 = h.get("relative_humidity_2m", [None] * len(h["time"]))[idx]
    pres0 = h.get("surface_pressure", [None] * len(h["time"]))[idx]
    # delay outlook: worst rain probability across the game window
    delay = None
    if not dome and hourly:
        worst = max((x["rain"] or 0) for x in hourly)
        level = ("clear" if worst < 20 else "watch" if worst < 45
                 else "likely" if worst < 70 else "severe")
        delay = dict(level=level, pct=worst)
    icon, sky = sky_of(cloud, pprob, fp_park.hour)
    if dome:
        icon, sky = "🏟️", "Indoor"

    hist = hist_all.get(home)
    game_id = f"{away.lower()}-{home.lower()}-{g.get('gamePk', 0) % 1000}"
    game_pk = g.get("gamePk")
    out = dict(id=game_id, away=away, home=home,
               park=meta["name"] + ("" if meta["roof"] == "open" else
                                    " · roof closed" if dome else " · roof open"),
               time=time_str, sortTime=sort_time,
               temp=temp, wind=0 if dome else wind, dir="—" if dome else deg_to_compass(wdir),
               windAngle=round(rel), windLabel="ROOF CLOSED" if dome else wind_label(rel),
               dew=dew, sky=sky, skyIcon=icon, dome=dome, gamePk=game_pk,
               rain=None if pprob is None else round(pprob),
               cloud=None if cloud is None else round(cloud),
               rh=None if rh0 is None else round(rh0),
               pres=None if pres0 is None else round(pres0),
               delay=delay, hourly=hourly or None)

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
        med = int(statistics.median(era_runs(x) for x in rows))
        candidates = [k + 0.5 for k in range(max(4, med - 3), med + 4)]
        def imbalance(L):
            o = sum(1 for x in rows if era_runs(x) > L); u = sum(1 for x in rows if era_runs(x) < L)
            return abs(o - u)
        line = min(candidates, key=imbalance)
    # era-adjusted totals: each matched game scaled to the current run environment
    over = sum(1 for x in rows if era_runs(x) > line)
    under = sum(1 for x in rows if era_runs(x) < line)
    push = n - over - under
    ou_median = round(statistics.median(era_runs(x) for x in rows), 1) if rows else None
    # a LEAN is only called when the matched sample's median clears the line
    # by a full run — percentages alone over-call (books already price weather)
    ou_lean = None
    if ou_median is not None and line:
        gap = ou_median - line
        ou_lean = "over" if gap >= 1.0 else ("under" if gap <= -1.0 else None)

    out.update(
        sample=n,
        hr=pct_delta(m_hr, avg["hr"]), runs=pct_delta(m_r, avg["r"]), ks=pct_delta(m_so, avg["so"]),
        hrGm=round(m_hr, 1), hrPark=avg["hr"], soPark=avg["so"],
        mlb=dict(hr=pct_delta(m_hr, league["hr"]), runs=pct_delta(m_r, league["r"]),
                 ks=pct_delta(m_so, league["so"])),
        ou=dict(over=round(over / n * 100) if n else 0,
                under=round(under / n * 100) if n else 0,
                push=max(0, 100 - (round(over / n * 100) + round(under / n * 100))) if n else 0),
        total=line or 0, lineSource=line_source, note=note,
        ouMedian=ou_median, ouLean=None if dome else ou_lean,
        matches=[dict(d=x["d"], t=x["t"], w=x["w"], r=x["r"], hr=x["hr"],
                      **({"p": x["p"]} if "p" in x else {}))
                 for x in sorted(rows, key=lambda x: x["d"], reverse=True)[:15]],
        rainHist=None if dome else wet_split(hist, line),
    )
    if dome:
        out["hr"] = out["runs"] = out["ks"] = 0

    # probable pitchers — real starts in similar conditions (display-only)
    pp_away = g["teams"]["away"].get("probablePitcher")
    pp_home = g["teams"]["home"].get("probablePitcher")
    if not offline and (pp_away or pp_home):
        seasons = [datetime.now(ET).year - 2, datetime.now(ET).year - 1,
                   datetime.now(ET).year]
        out["pitchers"] = dict(
            away=pitcher_conditions(pp_away, hist_all, temp, wind, dome, seasons),
            home=pitcher_conditions(pp_home, hist_all, temp, wind, dome, seasons))
    else:
        out["pitchers"] = None

    # conditions MVP — each team's best slugger in similar weather
    out["mvp"] = None if dome else dict(
        away=conditions_mvp(away, temp, wind, hitters_all),
        home=conditions_mvp(home, temp, wind, hitters_all))

    # plate umpire + park wind receptivity
    out["ump"] = ump_card(g, umps_all)
    out["windFx"] = None if (dome or not hist) else wind_receptivity(hist)
    return out

def archive_predictions(date_str, games):
    os.makedirs(PREDS_DIR, exist_ok=True)
    live = [g for g in games if not g.get("dome")]
    edge_pk = max(live, key=lambda g: abs(g["hr"]))["gamePk"] if live else None
    slim = [dict(gamePk=g.get("gamePk"), away=g["away"], home=g["home"],
                 total=g.get("total"), lineSource=g.get("lineSource"),
                 ou=g["ou"], ouLean=g.get("ouLean"), ouMedian=g.get("ouMedian"),
                 hr=g["hr"], runs=g["runs"], ks=g["ks"],
                 hrPark=g.get("hrPark"), soPark=g.get("soPark"),
                 edge=(g.get("gamePk") == edge_pk),
                 dome=g.get("dome", False), sample=g.get("sample"))
            for g in games]
    with open(os.path.join(PREDS_DIR, f"{date_str}.json"), "w") as f:
        json.dump(dict(date=date_str, games=slim), f, separators=(",", ":"))

def grade_day(date_str, preds):
    """Grade one archived day against official MLB final scores + box scores."""
    sched = get_json(SCHED_URL.format(date=date_str), tries=3)
    finals = {}
    for day in sched.get("dates", []):
        for g in day.get("games", []):
            if g.get("status", {}).get("abstractGameState") != "Final":
                continue
            a, h = g["teams"]["away"].get("score"), g["teams"]["home"].get("score")
            if a is not None and h is not None:
                finals[g["gamePk"]] = a + h
    graded = []
    for p in preds["games"]:
        pk = p.get("gamePk")
        if pk not in finals:
            continue
        total, line = finals[pk], p.get("total") or 0
        hr = so = None
        try:
            box = get_json(BOX_URL.format(pk=pk), tries=2)
            bt = box["teams"]
            hr = (bt["away"]["teamStats"]["batting"]["homeRuns"]
                  + bt["home"]["teamStats"]["batting"]["homeRuns"])
            so = (bt["away"]["teamStats"]["batting"]["strikeOuts"]
                  + bt["home"]["teamStats"]["batting"]["strikeOuts"])
            time.sleep(0.4)
        except Exception as e:
            print(f"    boxscore {pk}: {e}")
        ou_res = "push" if total == line else ("over" if total > line else "under")
        if "ouLean" in p:                      # v2: median-gap lean (era-adjusted)
            lean = p["ouLean"]
        else:                                  # legacy cards: percentage-margin lean
            lean = ("over" if p["ou"]["over"] > p["ou"]["under"] + 3
                    else "under" if p["ou"]["under"] > p["ou"]["over"] + 3 else None)
        lean_ok = None if (not lean or not line or ou_res == "push") else (lean == ou_res)
        # v2: ±15% trigger — graded results showed 8-15% calls hit only 20%
        hr_call = "boost" if p["hr"] >= 15 else ("suppress" if p["hr"] <= -15 else None)
        hr_ok = None
        if hr_call and hr is not None and p.get("hrPark"):
            hr_ok = (hr_call == ("boost" if hr > p["hrPark"] else "suppress"))
        k_call = "boost" if p["ks"] >= 6 else ("suppress" if p["ks"] <= -6 else None)
        k_ok = None
        if k_call and so is not None and p.get("soPark"):
            k_ok = (k_call == ("boost" if so > p["soPark"] else "suppress"))
        graded.append(dict(m=f'{p["away"]}@{p["home"]}', line=line, src=p.get("lineSource"),
                           total=total, ou=ou_res, lean=lean, leanOk=lean_ok,
                           hrPred=p["hr"], hrAct=hr, hrPark=p.get("hrPark"),
                           hrCall=hr_call, hrOk=hr_ok,
                           kPred=p["ks"], soAct=so, soPark=p.get("soPark"),
                           kCall=k_call, kOk=k_ok,
                           edge=p.get("edge", False), dome=p.get("dome", False)))
    return graded

def summarize(games):
    lw = sum(1 for g in games if g["leanOk"] is True)
    ll = sum(1 for g in games if g["leanOk"] is False)
    hw = sum(1 for g in games if g["hrOk"] is True)
    hl = sum(1 for g in games if g["hrOk"] is False)
    kw = sum(1 for g in games if g.get("kOk") is True)
    kl = sum(1 for g in games if g.get("kOk") is False)
    ew = sum(1 for g in games if g.get("edge") and g["hrOk"] is True)
    el = sum(1 for g in games if g.get("edge") and g["hrOk"] is False)
    errs = [abs(g["total"] - g["line"]) for g in games if g["line"]]
    return dict(n=len(games), leanW=lw, leanL=ll, hrW=hw, hrL=hl,
                kW=kw, kL=kl, edgeW=ew, edgeL=el,
                avgErr=round(sum(errs) / len(errs), 2) if errs else None)

def grade_pending(today_str):
    acc = json.load(open(ACCURACY)) if os.path.exists(ACCURACY) else {"days": {}}
    if not os.path.isdir(PREDS_DIR):
        return acc
    for fname in sorted(os.listdir(PREDS_DIR)):
        d = fname[:-5]
        if d >= today_str or d in acc["days"]:
            continue
        try:
            preds = json.load(open(os.path.join(PREDS_DIR, fname)))
            graded = grade_day(d, preds)
        except Exception as e:
            print(f"  grading {d} failed ({e}) — will retry next run")
            continue
        if graded:
            acc["days"][d] = dict(games=graded, summary=summarize(graded))
            print(f"  graded {d}: {acc['days'][d]['summary']}")
    allg = [g for day in acc["days"].values() for g in day["games"]]
    acc["cumulative"] = summarize(allg)
    acc["updated"] = today_str
    with open(ACCURACY, "w") as f:
        json.dump(acc, f, separators=(",", ":"))
    with open(SITE_ACCURACY, "w") as f:
        json.dump(acc, f, separators=(",", ":"))
    return acc

def make_brief(games):
    """Auto-generated slate write-up from today's data — no AI, just the numbers."""
    live = [g for g in games if not g["dome"]]
    parts = []
    if live:
        hot = max(live, key=lambda g: g["temp"])
        cool = min(live, key=lambda g: g["temp"])
        pk = lambda g: g["park"].split(" ·")[0]
        parts.append(f"Temps run from {cool['temp']}° at {pk(cool)} up to "
                     f"{hot['temp']}° at {pk(hot)}.")
        wind = max(live, key=lambda g: abs(g["hr"]))
        if abs(wind["hr"]) >= 10:
            verb = "boosting" if wind["hr"] > 0 else "cutting"
            parts.append(f"The wind story is {wind['away']} @ {wind['home']} — "
                         f"{wind['wind']} mph {wind['windLabel'].lower()} at {pk(wind)}, "
                         f"{verb} home-run expectation {abs(wind['hr'])}% vs that park's average.")
        else:
            parts.append("No standout wind edges on today's slate.")
        rain = sorted([g for g in live if (g.get("rain") or 0) >= 45],
                      key=lambda x: -x["rain"])
        if rain:
            parts.append("Rain risk: " + ", ".join(
                f"{g['away']} @ {g['home']} ({g['rain']}%)" for g in rain) +
                " — watch for delays.")
        else:
            parts.append("No serious rain threats.")
        und = max(live, key=lambda g: g["ou"]["under"])
        if und["ou"]["under"] >= 55:
            parts.append(f"Sharpest under environment: {und['away']} @ {und['home']}, "
                         f"under in {und['ou']['under']}% of similar-weather games.")
        ov = max(live, key=lambda g: g["ou"]["over"])
        if ov["ou"]["over"] >= 60:
            parts.append(f"Best over environment: {ov['away']} @ {ov['home']}, "
                         f"over {ov['ou']['over']}% historically.")
    domes = sum(1 for g in games if g["dome"])
    if domes:
        parts.append(f"{domes} roof{'s' if domes > 1 else ''} closed — "
                     "weather-neutral there.")
    return " ".join(parts)

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
    build_era_factors(hist_all)
    hitters_all = json.load(open(HITTERS)) if os.path.exists(HITTERS) else None
    umps_all = json.load(open(UMPS)) if os.path.exists(UMPS) else None
    if not umps_all:
        print("no umps_history.json yet — ump cards show name only until the "
              "'Build history' workflow reruns")
    if hitters_all:
        print(f"hitter history loaded (built {hitters_all.get('_built')})")
    else:
        print("no hitter history yet — Conditions MVP will be blank until the "
              "'Build hitter history' workflow runs")
    lines = {} if args.offline else fetch_book_lines()
    if os.path.exists(LINES):
        lines.update(json.load(open(LINES)))   # manual pins always win

    if args.offline:
        sched = json.load(open(os.path.join(FIXTURES, "schedule.json")))
    else:
        sched = get_json(SCHED_PP_URL.format(date=date_str))

    games = []
    for day in sched.get("dates", []):
        for g in day.get("games", []):
            try:
                built = build_game(g, hist_all, league, lines, args.offline, hitters_all, umps_all)
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
                   brief=make_brief(games),
                   games=sorted(games, key=lambda x: x["sortTime"]))
    with open(OUT, "w") as f:
        json.dump(payload, f, separators=(",", ":"))
    print(f"Wrote {OUT}: {len(games)} games for {date_str}")

    archive_predictions(date_str, games)
    if not args.offline:
        grade_pending(date_str)
    elif os.path.exists(ACCURACY):
        import shutil; shutil.copy(ACCURACY, SITE_ACCURACY)

if __name__ == "__main__":
    main()
