#!/usr/bin/env python3
"""Build the historical park/weather dataset.

For every team's CURRENT park, collect every regular-season game since the park
qualified (see parks.py), with per-game runs, home runs, and strikeouts from
Retrosheet game logs, joined to the historical hourly weather at that park from
the Open-Meteo archive API.

Output: data/parks_history.json
  { "<TEAM>": { "games": [ {d, dn, t, dew, w, rel, r, hr, so}, ... ],
                "avg":   {r, hr, so, n} },
    "_league": {r, hr, so, n},
    "_built":  "YYYY-MM-DD", "_seasons": [..] }

Game fields: d=YYYYMMDD, dn=D/N, t=temp°F, dew=dewpoint°F, w=wind mph,
rel=wind blow-toward angle relative to CF axis (deg), p=precip inches over
the ~3h game window (0 = dry), r=total runs, hr=total HRs, so=total strikeouts.

No third-party dependencies — runs on a bare GitHub Actions Python.
"""
import csv, functools, io, json, os, statistics, sys, time, urllib.request, zipfile
from datetime import date
sys.path.insert(0, os.path.dirname(__file__))
from parks import PARKS, RETRO_TO_CODE, wind_rel_angle

print = functools.partial(print, flush=True)   # live logs on CI

SEASONS = list(range(2019, date.today().year))   # completed seasons only
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "parks_history.json")

GL_URL = "https://www.retrosheet.org/gamelogs/gl{year}.zip"
ARCHIVE_URL = ("https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lon}"
               "&start_date={start}&end_date={end}"
               "&hourly=temperature_2m,dew_point_2m,wind_speed_10m,wind_direction_10m,precipitation"
               "&temperature_unit=fahrenheit&wind_speed_unit=mph&precipitation_unit=inch&timezone={tz}")

# Retrosheet game-log fixed field positions (0-indexed). See glfields.txt.
F_DATE, F_VTEAM, F_HTEAM, F_VSCORE, F_HSCORE, F_DAYNIGHT = 0, 3, 6, 9, 10, 12
F_VHR, F_VSO, F_HHR, F_HSO = 25, 32, 53, 60

CHADWICK_URL = "https://raw.githubusercontent.com/chadwickbureau/retrosheet/master/gamelog/GL{year}.TXT"

def fetch(url, tries=4, timeout=60):
    for i in range(tries):
        try:
            t0 = time.time()
            req = urllib.request.Request(url, headers={"User-Agent": "weatheredge-build/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
            print(f"    fetched {url.split('?')[0]} ({len(data)//1024} KB, {time.time()-t0:.1f}s)")
            return data
        except Exception as e:
            print(f"    retry {i+1}/{tries} for {url.split('?')[0]}: {e}")
            if i == tries - 1:
                raise
            time.sleep(8 * (i + 1))

def load_season(year):
    # Prefer retrosheet.org; fall back to the Chadwick Bureau GitHub mirror,
    # which is fast and reliable from CI runners.
    try:
        raw = fetch(GL_URL.format(year=year), tries=2, timeout=45)
        zf = zipfile.ZipFile(io.BytesIO(raw))
        name = [n for n in zf.namelist() if n.lower().endswith(".txt")][0]
        data = zf.read(name)
    except Exception as e:
        print(f"  {year}: retrosheet.org unavailable ({e}); using Chadwick mirror")
        data = fetch(CHADWICK_URL.format(year=year), tries=3, timeout=45)
    rows = list(csv.reader(io.TextIOWrapper(io.BytesIO(data), encoding="latin-1")))
    return rows

def season_games(year):
    """Yield (team_code, yyyymmdd, day_night, runs, hr, so) for qualifying games."""
    rows = load_season(year)
    total_hr = 0
    kept = []
    for row in rows:
        try:
            d = row[F_DATE]
            home_retro = row[F_HTEAM]
            runs = int(row[F_VSCORE]) + int(row[F_HSCORE])
            hr = int(row[F_VHR]) + int(row[F_HHR])
            so = int(row[F_VSO]) + int(row[F_HSO])
            dn = row[F_DAYNIGHT].strip().upper() or "N"
        except (ValueError, IndexError):
            continue
        total_hr += hr
        code = RETRO_TO_CODE.get(home_retro)
        if not code:
            continue
        meta = PARKS[code]
        if year < meta["since"] or year in meta["exclude"]:
            continue
        kept.append((code, d, dn, runs, hr, so))
    # Sanity: league HR totals per full season have been ~4400-7000 since 2019.
    if year != 2020 and not (3500 < total_hr < 8000):
        raise SystemExit(f"SANITY FAIL {year}: parsed league HR total {total_hr} — "
                         "Retrosheet field layout may have changed; aborting.")
    print(f"  {year}: {len(kept)} qualifying games (league HR parsed: {total_hr})")
    return kept

def park_weather(code, years):
    """Hourly weather dict keyed 'YYYY-MM-DDTHH' for the park, local time."""
    meta = PARKS[code]
    out = {}
    # chunk by 2 seasons per request — smaller responses are served faster
    for i in range(0, len(years), 2):
        chunk = years[i:i+2]
        url = ARCHIVE_URL.format(lat=meta["lat"], lon=meta["lon"],
                                 start=f"{chunk[0]}-03-01", end=f"{chunk[-1]}-11-15",
                                 tz=meta["tz"].replace("/", "%2F"))
        data = json.loads(fetch(url))
        h = data["hourly"]
        prec = h.get("precipitation", [None] * len(h["time"]))
        for t, temp, dew, ws, wd, pr in zip(h["time"], h["temperature_2m"],
                                            h["dew_point_2m"], h["wind_speed_10m"],
                                            h["wind_direction_10m"], prec):
            out[t[:13]] = (temp, dew, ws, wd, pr)
        time.sleep(1.5)
    return out

def main():
    print("Loading Retrosheet game logs…")
    by_park = {}
    seasons_used = []
    for year in SEASONS:
        try:
            games = season_games(year)
            seasons_used.append(year)
        except Exception as e:
            print(f"  {year}: unavailable ({e}) — skipping")
            continue
        for code, d, dn, runs, hr, so in games:
            by_park.setdefault(code, []).append((d, dn, runs, hr, so))

    print("Joining historical weather per park…")
    history = {}
    league = {"r": [], "hr": [], "so": []}
    for code, games in sorted(by_park.items()):
        meta = PARKS[code]
        years = sorted({int(d[:4]) for d, *_ in games})
        wx = park_weather(code, years)
        rows = []
        for d, dn, runs, hr, so in games:
            hour = 13 if dn == "D" else 19
            day_key = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
            w = wx.get(f"{day_key}T{hour:02d}")
            if not w or any(v is None for v in w[:4]):
                continue
            temp, dew, ws, wd, _ = w
            # precip over the ~3h game window (first pitch + 2h)
            precip = 0.0
            for hh in range(hour, hour + 3):
                slot = wx.get(f"{day_key}T{hh:02d}")
                if slot and slot[4] is not None:
                    precip += slot[4]
            rel = round(wind_rel_angle(wd, meta["bearing"]))
            rows.append(dict(d=d, dn=dn, t=round(temp), dew=round(dew),
                             w=round(ws), rel=rel, p=round(precip, 2),
                             r=runs, hr=hr, so=so))
            league["r"].append(runs); league["hr"].append(hr); league["so"].append(so)
        avg = dict(r=round(statistics.mean(x["r"] for x in rows), 2),
                   hr=round(statistics.mean(x["hr"] for x in rows), 2),
                   so=round(statistics.mean(x["so"] for x in rows), 2),
                   n=len(rows)) if rows else dict(r=0, hr=0, so=0, n=0)
        history[code] = dict(games=rows, avg=avg)
        print(f"  {code}: {len(rows)} games with weather")

    history["_league"] = dict(r=round(statistics.mean(league["r"]), 2),
                              hr=round(statistics.mean(league["hr"]), 2),
                              so=round(statistics.mean(league["so"]), 2),
                              n=len(league["r"]))
    history["_built"] = date.today().isoformat()
    history["_seasons"] = seasons_used
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(history, f, separators=(",", ":"))
    print(f"Wrote {OUT} — league avgs {history['_league']}")

if __name__ == "__main__":
    main()
