#!/usr/bin/env python3
"""Build the NFL stadium/weather history dataset.

Source: the nflverse games file (free, community-maintained) — every game
since 1999 with final scores, stadium, roof state, and REAL closing betting
totals. We keep 2015-present home games at each team's current stadium and
join each outdoor game to Open-Meteo's hourly archive at kickoff.

Output: data/nfl/stadiums_history.json
  { "<TEAM>": { "games": [ {d, t, w, ax, pts, line, res, dome}, ... ],
                "avg": {pts, n} },
    "_league": {pts, n}, "_built": "...", "_seasons": [..] }

Game fields: d=YYYYMMDD, t=temp°F, w=wind mph, ax=wind angle vs field axis
(0=along, 90=crosswind), pts=total points, line=closing total,
res=over/under/push vs that game's own closing line, dome=roof closed.

No third-party dependencies.
"""
import csv, functools, io, json, os, statistics, sys, time, urllib.request
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(__file__))
from stadiums import STADIUMS, axis_angle

print = functools.partial(print, flush=True)

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
OUT = os.path.join(ROOT, "data", "nfl", "stadiums_history.json")

GAMES_URL = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
ARCHIVE_URL = ("https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lon}"
               "&start_date={start}&end_date={end}"
               "&hourly=temperature_2m,wind_speed_10m,wind_direction_10m"
               "&temperature_unit=fahrenheit&wind_speed_unit=mph&timezone={tz}")

FIRST_SEASON = 2015


def fetch(url, tries=4, timeout=60):
    for i in range(tries):
        try:
            t0 = time.time()
            req = urllib.request.Request(url, headers={"User-Agent": "dfsradar-build/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
            print(f"    fetched {url.split('?')[0]} ({len(data)//1024} KB, {time.time()-t0:.1f}s)")
            return data
        except Exception as e:
            print(f"    retry {i+1}/{tries}: {e}")
            if i == tries - 1:
                raise
            time.sleep(8 * (i + 1))


def load_games():
    raw = fetch(GAMES_URL, timeout=90)
    rows = list(csv.DictReader(io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8")))
    kept = []
    for r in rows:
        try:
            season = int(r["season"])
        except (ValueError, KeyError):
            continue
        if season < FIRST_SEASON:
            continue
        home = r.get("home_team", "")
        meta = STADIUMS.get(home)
        if not meta or season < meta["since"] or season in meta["exclude"]:
            continue
        if (r.get("location") or "Home") != "Home":
            continue          # neutral-site / international games: wrong venue
        hs, as_ = r.get("home_score"), r.get("away_score")
        if not hs or not as_:
            continue          # future / unplayed
        roof = (r.get("roof") or "").strip().lower()
        dome = roof in ("dome", "closed")
        try:
            line = float(r["total_line"]) if r.get("total_line") else None
        except ValueError:
            line = None
        kept.append(dict(team=home, day=r["gameday"], time=r.get("gametime") or "13:00",
                         pts=int(float(hs)) + int(float(as_)), dome=dome, line=line,
                         season=season))
    print(f"nflverse: {len(kept)} qualifying home games since {FIRST_SEASON}")
    if not (1500 < len(kept) < 6000):
        raise SystemExit(f"SANITY FAIL: {len(kept)} games parsed — column layout may have changed")
    return kept


def stadium_weather(meta, years):
    out = {}
    for i in range(0, len(years), 4):
        chunk = years[i:i + 4]
        url = ARCHIVE_URL.format(lat=meta["lat"], lon=meta["lon"],
                                 start=f"{chunk[0]}-08-01", end=f"{chunk[-1]}-12-31" if chunk[-1] < date.today().year else date.today().isoformat(),
                                 tz=meta["tz"].replace("/", "%2F"))
        data = json.loads(fetch(url))
        h = data["hourly"]
        for t, temp, ws, wd in zip(h["time"], h["temperature_2m"],
                                   h["wind_speed_10m"], h["wind_direction_10m"]):
            out[t[:13]] = (temp, ws, wd)
        time.sleep(1.2)
    return out


def main():
    games = load_games()
    by_team = {}
    for g in games:
        by_team.setdefault(g["team"], []).append(g)

    # SoFi is shared: LA + LAC both resolve there but keep separate team keys
    history = {}
    league_pts = []
    for team, tgames in sorted(by_team.items()):
        meta = STADIUMS[team]
        # NFL season spans Sep-Feb: a January game belongs to the prior season's
        # year+1 — collect the actual calendar years present
        years = sorted({int(g["day"][:4]) for g in tgames})
        wx = stadium_weather(meta, years)
        rows = []
        for g in tgames:
            d = g["day"].replace("-", "")
            hour = 13
            try:
                hour = int(g["time"].split(":")[0])
                # gametime is US/Eastern; shift to stadium-local wall clock
                et_offsets = {"America/New_York": 0, "America/Detroit": 0,
                              "America/Chicago": -1, "America/Denver": -2,
                              "America/Phoenix": -2, "America/Los_Angeles": -3,
                              "America/Indiana/Indianapolis": 0}
                hour = max(0, min(23, hour + et_offsets.get(meta["tz"], 0)))
            except (ValueError, IndexError):
                pass
            key = f"{g['day']}T{hour:02d}"
            w = wx.get(key)
            if not w or any(v is None for v in w):
                continue
            temp, ws, wd = w
            res = None
            if g["line"] is not None:
                res = ("push" if g["pts"] == g["line"]
                       else "over" if g["pts"] > g["line"] else "under")
            rows.append(dict(d=d, t=round(temp), w=round(ws),
                             ax=round(axis_angle(wd, meta["bearing"])),
                             pts=g["pts"], line=g["line"], res=res,
                             dome=g["dome"]))
            league_pts.append(g["pts"])
        avg = dict(pts=round(statistics.mean(x["pts"] for x in rows), 1),
                   n=len(rows)) if rows else dict(pts=0, n=0)
        history[team] = dict(games=rows, avg=avg)
        print(f"  {team}: {len(rows)} games with weather ({meta['name']})")

    history["_league"] = dict(pts=round(statistics.mean(league_pts), 1), n=len(league_pts))
    history["_built"] = date.today().isoformat()
    history["_seasons"] = [FIRST_SEASON, date.today().year - 1]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(history, f, separators=(",", ":"))
    print(f"Wrote {OUT} — league avg {history['_league']}")


if __name__ == "__main__":
    main()
