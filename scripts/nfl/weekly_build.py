#!/usr/bin/env python3
"""NFL weekly slate build: upcoming games + kickoff forecasts + similar-weather
history -> site/nfl/data.json (consumed by site/nfl/index.html).

Schedule comes from the nflverse games file (includes the full upcoming
season). Weather from Open-Meteo (16-day horizon covers the week). Totals
from The Odds API (same key as MLB — americanfootball_nfl).

The NFL edge over our MLB pipeline: history carries REAL closing totals for
every past game, so O/U hit rates are measured against the lines that
actually existed.

Usage:
  python scripts/nfl/weekly_build.py            # next 8 days
  python scripts/nfl/weekly_build.py --offline  # fixture-free sample guard

No third-party dependencies.
"""
import argparse, csv, functools, io, json, os, statistics, sys, time
import urllib.error, urllib.request
from datetime import datetime, timedelta, timezone

print = functools.partial(print, flush=True)
sys.path.insert(0, os.path.dirname(__file__))
from stadiums import STADIUMS, axis_angle, wind_class

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
HISTORY = os.path.join(ROOT, "data", "nfl", "stadiums_history.json")
OUT = os.path.join(ROOT, "site", "nfl", "data.json")

GAMES_URL = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
FC_URL = ("https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
          "&hourly=temperature_2m,dew_point_2m,wind_speed_10m,wind_direction_10m,"
          "cloud_cover,precipitation_probability,relative_humidity_2m,surface_pressure"
          "&temperature_unit=fahrenheit&wind_speed_unit=mph&timezone={tz}&forecast_days=16")
ODDS_URL = ("https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds"
            "?apiKey={key}&regions=us&markets=totals&oddsFormat=american")

ODDS_TEAM_NAMES = {
    "Arizona Cardinals":"ARI","Atlanta Falcons":"ATL","Baltimore Ravens":"BAL",
    "Buffalo Bills":"BUF","Carolina Panthers":"CAR","Chicago Bears":"CHI",
    "Cincinnati Bengals":"CIN","Cleveland Browns":"CLE","Dallas Cowboys":"DAL",
    "Denver Broncos":"DEN","Detroit Lions":"DET","Green Bay Packers":"GB",
    "Houston Texans":"HOU","Indianapolis Colts":"IND","Jacksonville Jaguars":"JAX",
    "Kansas City Chiefs":"KC","Las Vegas Raiders":"LV","Los Angeles Chargers":"LAC",
    "Los Angeles Rams":"LA","Miami Dolphins":"MIA","Minnesota Vikings":"MIN",
    "New England Patriots":"NE","New Orleans Saints":"NO","New York Giants":"NYG",
    "New York Jets":"NYJ","Philadelphia Eagles":"PHI","Pittsburgh Steelers":"PIT",
    "San Francisco 49ers":"SF","Seattle Seahawks":"SEA","Tampa Bay Buccaneers":"TB",
    "Tennessee Titans":"TEN","Washington Commanders":"WAS",
}

ET = timezone(timedelta(hours=-4))
ET_OFFSETS = {"America/New_York": 0, "America/Detroit": 0, "America/Chicago": -1,
              "America/Denver": -2, "America/Phoenix": -2, "America/Los_Angeles": -3,
              "America/Indiana/Indianapolis": 0}


def get_json(url, tries=5):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "dfsradar-build/1.0"})
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read())
        except Exception as e:
            if i == tries - 1:
                raise
            wait = 45 if (isinstance(e, urllib.error.HTTPError) and e.code == 429) else 8 * (i + 1)
            print(f"    retry {i+1}/{tries} in {wait}s: {e}")
            time.sleep(wait)


def fetch_book_totals():
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        print("odds api: no key — no live totals")
        return {}
    try:
        events = get_json(ODDS_URL.format(key=key), tries=3)
    except Exception as e:
        print(f"odds api unavailable ({e})")
        return {}
    out = {}
    for ev in events:
        a, h = ODDS_TEAM_NAMES.get(ev.get("away_team")), ODDS_TEAM_NAMES.get(ev.get("home_team"))
        if not a or not h:
            continue
        pts = [oc["point"] for bk in ev.get("bookmakers", []) for mk in bk.get("markets", [])
               if mk.get("key") == "totals" for oc in mk.get("outcomes", [])
               if oc.get("name") == "Over" and oc.get("point") is not None]
        if pts:
            out[f"{a}@{h}"] = statistics.median(pts)
    print(f"odds api: totals for {len(out)} NFL games")
    return out


def load_upcoming(window_days=8):
    raw = urllib.request.urlopen(
        urllib.request.Request(GAMES_URL, headers={"User-Agent": "dfsradar-build/1.0"}),
        timeout=90).read()
    rows = list(csv.DictReader(io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8")))
    today = datetime.now(ET).date()
    end = today + timedelta(days=window_days)
    out = []
    for r in rows:
        day = r.get("gameday") or ""
        try:
            d = datetime.strptime(day, "%Y-%m-%d").date()
        except ValueError:
            continue
        if not (today <= d <= end):
            continue
        if r.get("home_score"):
            continue                       # already played
        out.append(r)
    print(f"upcoming games in window: {len(out)}")
    return out


_FC = {}
def forecast(meta):
    k = meta["name"]
    if k not in _FC:
        _FC[k] = get_json(FC_URL.format(lat=meta["lat"], lon=meta["lon"],
                                        tz=meta["tz"].replace("/", "%2F")))
        time.sleep(1)
    return _FC[k]


def sky_of(cloud, pp, hour):
    night = hour >= 20 or hour < 6
    if pp is not None and pp >= 55: return ("🌧️", "Rain risk")
    if cloud is None: return ("🌤️", "—")
    if cloud >= 85: return ("☁️", "Overcast")
    if cloud >= 45: return ("🌙", "Partly cloudy") if night else ("⛅", "Partly cloudy")
    return ("🌙", "Clear") if night else ("☀️", "Sunny")


def wind_receptivity(games):
    """Points vs wind speed at this stadium (outdoor games)."""
    rows = [g for g in games if not g.get("dome")]
    if len(rows) < 60:
        return None
    xs = [g["w"] for g in rows]; ys = [g["pts"] for g in rows]
    n = len(xs); mx, my = sum(xs)/n, sum(ys)/n
    sxx = sum((x-mx)**2 for x in xs)
    if not sxx or not my:
        return None
    slope = sum((x-mx)*(y-my) for x, y in zip(xs, ys)) / sxx
    pct10 = round(slope * 10 / my * 100)
    a = abs(pct10)
    rating = "LOW" if a < 4 else "MEDIUM" if a < 8 else "HIGH" if a < 13 else "EXTREME"
    return dict(rating=rating, pct10=pct10)


def match_games(hist_games, temp, wind, ax, dome):
    if dome:
        return [g for g in hist_games if g.get("dome")], "indoor games (roof closed)"
    wc = wind_class(ax)
    pool = [g for g in hist_games if not g.get("dome")]
    for dt, dw, use_class in ((10, 6, True), (12, 8, True), (15, 99, False)):
        rows = [g for g in pool
                if abs(g["t"] - temp) <= dt and abs(g["w"] - wind) <= dw
                and (not use_class or wind_class(g["ax"]) == wc)]
        if len(rows) >= 10:
            note = (f"±{dt}° temp, ±{dw} mph, {wc} wind" if use_class
                    else f"±{dt}° temp (widened)")
            return rows, note
    return rows, "small sample — widest window"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()

    hist_all = json.load(open(HISTORY)) if os.path.exists(HISTORY) else None
    if not hist_all:
        sys.exit("data/nfl/stadiums_history.json missing — run the NFL history workflow first.")
    league = hist_all["_league"]

    upcoming = [] if args.offline else load_upcoming()
    totals = {} if args.offline else fetch_book_totals()

    games = []
    for r in upcoming:
        home, away = r["home_team"], r["away_team"]
        meta = STADIUMS.get(home)
        if not meta:
            continue
        neutral = (r.get("location") or "Home") != "Home"
        gt = r.get("gametime") or "13:00"
        try:
            et_h, et_m = int(gt.split(":")[0]), int(gt.split(":")[1])
        except (ValueError, IndexError):
            et_h, et_m = 13, 0
        local_h = max(0, min(23, et_h + ET_OFFSETS.get(meta["tz"], 0)))
        day = r["gameday"]
        d_obj = datetime.strptime(day, "%Y-%m-%d")
        roof = meta["roof"]
        dome = roof == "dome" or (roof == "retract")   # retractables default closed for NFL

        fc = forecast(meta)
        h = fc["hourly"]
        want = f"{day}T{local_h:02d}"
        idx = next((i for i, t in enumerate(h["time"]) if t.startswith(want)), None)
        if idx is None:
            print(f"  no forecast slot for {away}@{home} {want} — beyond horizon?")
            continue
        temp = round(h["temperature_2m"][idx]); dew = round(h["dew_point_2m"][idx])
        wind = round(h["wind_speed_10m"][idx]); wdir = h["wind_direction_10m"][idx]
        cloud = h["cloud_cover"][idx]; pp = h["precipitation_probability"][idx]
        rh = h["relative_humidity_2m"][idx]; pres = h["surface_pressure"][idx]
        ax = round(axis_angle(wdir, meta["bearing"]))
        icon, sky = ("🏟️", "Indoor") if dome else sky_of(cloud, pp, local_h)

        hourly = []
        if not dome:
            for off in range(-1, 4):
                j = idx + off
                if j < 0 or j >= len(h["time"]):
                    continue
                hh = datetime.fromisoformat(h["time"][j])
                ic, _ = sky_of(h["cloud_cover"][j], h["precipitation_probability"][j], hh.hour)
                hourly.append(dict(
                    lab=hh.strftime("%-I %p"), fp=(off == 0), c=ic,
                    t=round(h["temperature_2m"][j]), w=round(h["wind_speed_10m"][j]),
                    ax=round(axis_angle(h["wind_direction_10m"][j], meta["bearing"])),
                    rain=None if h["precipitation_probability"][j] is None else round(h["precipitation_probability"][j]),
                    rh=None if h["relative_humidity_2m"][j] is None else round(h["relative_humidity_2m"][j])))
        delay = None
        if not dome and hourly:
            worst = max((x["rain"] or 0) for x in hourly)
            delay = dict(level=("clear" if worst < 20 else "watch" if worst < 45
                                else "likely" if worst < 70 else "severe"), pct=worst)

        hist = hist_all.get(home, {"games": [], "avg": {"pts": 0, "n": 0}})
        rows, note = match_games(hist["games"], temp, wind, ax, dome)
        n = len(rows)
        m_pts = statistics.mean(x["pts"] for x in rows) if rows else 0
        avg_pts = hist["avg"]["pts"] or league["pts"]
        # O/U measured against each matched game's OWN closing line — real hit rates
        lined = [x for x in rows if x.get("res")]
        overs = sum(1 for x in lined if x["res"] == "over")
        unders = sum(1 for x in lined if x["res"] == "under")
        pushes = len(lined) - overs - unders
        today_line = totals.get(f"{away}@{home}")

        wc = wind_class(ax)
        wind_label = ("ROOF CLOSED" if dome else
                      {"along": "down the field axis", "cross": "crosswind",
                       "angled": "quartering wind"}[wc])
        games.append(dict(
            id=f"{away.lower()}-{home.lower()}-{day.replace('-','')}",
            away=away, home=home, week=r.get("week"),
            stadium=meta["name"] + (" · roof closed" if dome and roof != "dome" else ""),
            day=d_obj.strftime("%a %b %-d"), time=f"{et_h % 12 or 12}:{et_m:02d} {'PM' if et_h >= 12 else 'AM'} ET",
            sortTime=day + gt, neutral=neutral,
            temp=temp, dew=dew, wind=0 if dome else wind, ax=ax, windClass=wc,
            windLabel=wind_label, sky=sky, skyIcon=icon, dome=dome,
            rain=None if pp is None else round(pp),
            rh=None if rh is None else round(rh),
            pres=None if pres is None else round(pres),
            hourly=hourly or None, delay=delay,
            sample=n, pts=round((m_pts - avg_pts) / avg_pts * 100) if avg_pts and n else 0,
            ptsGm=round(m_pts, 1), ptsStad=avg_pts,
            ou=dict(over=round(overs / len(lined) * 100) if lined else 0,
                    under=round(unders / len(lined) * 100) if lined else 0,
                    push=round(pushes / len(lined) * 100) if lined else 0,
                    n=len(lined)),
            total=today_line, lineSource="book" if today_line else None,
            note=note, windFx=None if dome else wind_receptivity(hist["games"]),
            matches=[dict(d=x["d"], t=x["t"], w=x["w"], ax=x["ax"], pts=x["pts"],
                          line=x["line"], res=x["res"])
                     for x in sorted(rows, key=lambda x: x["d"], reverse=True)[:15]],
        ))
        if dome:
            games[-1]["pts"] = 0

    # slate brief
    parts = []
    live = [g for g in games if not g["dome"]]
    if live:
        cold = min(live, key=lambda g: g["temp"]); windy = max(live, key=lambda g: g["wind"])
        parts.append(f"Coldest kickoff: {cold['temp']}° for {cold['away']} @ {cold['home']}.")
        if windy["wind"] >= 12:
            parts.append(f"Wind watch: {windy['wind']} mph {windy['windLabel']} for "
                         f"{windy['away']} @ {windy['home']} at {windy['stadium'].split(' ·')[0]}.")
        rain = sorted([g for g in live if (g.get('rain') or 0) >= 45], key=lambda x: -x['rain'])
        if rain:
            parts.append("Rain risk: " + ", ".join(f"{g['away']} @ {g['home']} ({g['rain']}%)"
                                                   for g in rain) + ".")
        else:
            parts.append("No serious rain threats on the slate.")
    domes = sum(1 for g in games if g["dome"])
    if domes:
        parts.append(f"{domes} game{'s' if domes > 1 else ''} under a roof — weather-neutral.")

    payload = dict(generated=datetime.now(ET).strftime("%Y-%m-%d %H:%M ET"),
                   league=league, seasons=hist_all.get("_seasons"),
                   brief=" ".join(parts),
                   games=sorted(games, key=lambda x: x["sortTime"]))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(payload, f, separators=(",", ":"))
    print(f"Wrote {OUT}: {len(games)} games")


if __name__ == "__main__":
    main()
