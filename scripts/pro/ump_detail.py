#!/usr/bin/env python3
"""DFSRADAR PRO — umpire detail dataset.

Builds the deep umpire layer behind the PRO page:
  * career HR/game vs league for every plate ump (2017 -> today)
  * per-park splits (ump x park, min 5 games)
  * last-5-games hot/cold streak vs career
  * runs/game tendency (for the totals projection)
  * full leaderboard + league context stats

Sources:
  2017-2025  Retrosheet game logs (plate ump, HRs, runs per game) —
             parsed once, cached in data/pro/ump_games_retro.json
  2026       MLB Stats API schedule per date with hydrate=officials,scoringplays
             (plate ump, HR count from scoring plays, runs, gamePk) —
             cached per date in data/pro/ump_games_2026.json, so the daily
             run only fetches yesterday. First run backfills the season.

Outputs:
  site/pro/umps.json            display dataset (deployed with the site)
  data/pro/ump_games_retro.json committed cache (build once)
  data/pro/ump_games_2026.json  committed cache (grows daily)

The with-ump split joins in scripts/pro/build.py read both caches directly.
No third-party dependencies.
"""
import csv, functools, io, json, os, sys, time, urllib.request, zipfile
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from parks import RETRO_TO_CODE, MLBID_TO_CODE

print = functools.partial(print, flush=True)

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
RETRO_CACHE = os.path.join(ROOT, "data", "pro", "ump_games_retro.json")
S2026_CACHE = os.path.join(ROOT, "data", "pro", "ump_games_2026.json")
OUT = os.path.join(ROOT, "site", "pro", "umps.json")

ET = timezone(timedelta(hours=-4))
RETRO_SEASONS = list(range(2017, 2026))          # 2017-2025 inclusive
SEASON_2026_START = date(2026, 3, 20)

GL_URL = "https://www.retrosheet.org/gamelogs/gl{year}.zip"
CHADWICK_URL = "https://raw.githubusercontent.com/chadwickbureau/retrosheet/master/gamelog/GL{year}.TXT"
SCHED_URL = ("https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={d}"
             "&hydrate=officials,scoringplays")

# Retrosheet fixed fields
F_DATE, F_VTEAM, F_HTEAM, F_VSCORE, F_HSCORE = 0, 3, 6, 9, 10
F_VHR, F_HHR = 25, 53
F_UMP_NAME = 78


def fetch(url, tries=4, timeout=60):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "dfsradar-pro/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:
            if i == tries - 1:
                raise
            print(f"    retry {i+1}/{tries}: {e}")
            time.sleep(6 * (i + 1))


def get_json(url, tries=4):
    return json.loads(fetch(url, tries=tries, timeout=45))


def build_retro_cache():
    """Parse Retrosheet 2017-2025 once -> [[yyyymmdd, home, away, ump, hr, runs], ...]"""
    if os.path.exists(RETRO_CACHE):
        c = json.load(open(RETRO_CACHE))
        if c.get("seasons") == RETRO_SEASONS:
            print(f"retro cache ok ({len(c['games'])} games)")
            return c["games"]
    games = []
    for year in RETRO_SEASONS:
        try:
            raw = fetch(GL_URL.format(year=year), tries=2, timeout=45)
            zf = zipfile.ZipFile(io.BytesIO(raw))
            name = [n for n in zf.namelist() if n.lower().endswith(".txt")][0]
            data = zf.read(name)
        except Exception as e:
            print(f"  {year}: retrosheet.org unavailable ({e}); using Chadwick mirror")
            data = fetch(CHADWICK_URL.format(year=year), tries=3, timeout=45)
        rows = list(csv.reader(io.TextIOWrapper(io.BytesIO(data), encoding="latin-1")))
        n0, hr_total = len(games), 0
        for row in rows:
            try:
                d = row[F_DATE]
                home = RETRO_TO_CODE.get(row[F_HTEAM])
                away = RETRO_TO_CODE.get(row[F_VTEAM])
                runs = int(row[F_VSCORE]) + int(row[F_HSCORE])
                hr = int(row[F_VHR]) + int(row[F_HHR])
                ump = row[F_UMP_NAME].strip()
            except (ValueError, IndexError):
                continue
            hr_total += hr
            if not home or not away or not ump or " " not in ump or ump == "(none)":
                continue
            games.append([d, home, away, ump, hr, runs])
        if year != 2020 and not (3500 < hr_total < 8000):
            raise SystemExit(f"SANITY FAIL {year}: league HR total {hr_total}")
        print(f"  {year}: {len(games)-n0} games (league HR {hr_total})")
    os.makedirs(os.path.dirname(RETRO_CACHE), exist_ok=True)
    with open(RETRO_CACHE, "w") as f:
        json.dump(dict(seasons=RETRO_SEASONS, games=games), f, separators=(",", ":"))
    print(f"Wrote {RETRO_CACHE}: {len(games)} games")
    return games


def plate_ump(g):
    for o in g.get("officials") or []:
        if (o.get("officialType") or "").lower() == "home plate":
            return (o.get("official") or {}).get("fullName")
    return None


def hr_count(g):
    n = 0
    for p in (g.get("scoringPlays") or []):
        if ((p.get("result") or {}).get("event") or "") == "Home Run":
            n += 1
    return n


def build_2026_cache():
    """Per-date cache: {date: [[home, away, ump, hr, runs, gamePk], ...]}"""
    cache = json.load(open(S2026_CACHE)) if os.path.exists(S2026_CACHE) else {}
    yesterday = (datetime.now(ET) - timedelta(days=1)).date()
    d = SEASON_2026_START
    missing = []
    while d <= yesterday:
        if d.isoformat() not in cache:
            missing.append(d)
        d += timedelta(days=1)
    if missing:
        print(f"2026 cache: fetching {len(missing)} dates")
    for i, d in enumerate(missing):
        try:
            sched = get_json(SCHED_URL.format(d=d.isoformat()))
        except Exception as e:
            print(f"  {d}: schedule unavailable ({e}) — will retry next run")
            continue
        rows = []
        for day in sched.get("dates", []):
            for g in day.get("games", []):
                if g.get("gameType") != "R":
                    continue
                if (g.get("status") or {}).get("abstractGameState") != "Final":
                    continue
                ump = plate_ump(g)
                th, ta = g["teams"]["home"], g["teams"]["away"]
                home = MLBID_TO_CODE.get((th.get("team") or {}).get("id"))
                away = MLBID_TO_CODE.get((ta.get("team") or {}).get("id"))
                if not ump or not home or not away:
                    continue
                runs = (th.get("score") or 0) + (ta.get("score") or 0)
                rows.append([home, away, ump, hr_count(g), runs, g.get("gamePk") or 0])
        cache[d.isoformat()] = rows
        if i % 20 == 0 and i:
            print(f"  ...{i}/{len(missing)}")
        time.sleep(0.15)
    os.makedirs(os.path.dirname(S2026_CACHE), exist_ok=True)
    with open(S2026_CACHE, "w") as f:
        json.dump(cache, f, separators=(",", ":"))
    total = sum(len(v) for v in cache.values())
    print(f"2026 cache: {len(cache)} dates, {total} final games")
    return cache


def main():
    retro = build_retro_cache()
    c2026 = build_2026_cache()

    # unified rows: (yyyymmdd, home, away, ump, hr, runs)
    rows = [(g[0], g[1], g[2], g[3], g[4], g[5]) for g in retro]
    for dstr, games in c2026.items():
        d = dstr.replace("-", "")
        for home, away, ump, hr, runs, _pk in games:
            rows.append((d, home, away, ump, hr, runs))

    total_g = len(rows)
    total_hr = sum(r[4] for r in rows)
    total_r = sum(r[5] for r in rows)
    lg_hrpg = total_hr / total_g
    lg_rpg = total_r / total_g

    umps = {}
    for d, home, away, ump, hr, runs in rows:
        u = umps.setdefault(ump, dict(n=0, hr=0, r=0, parks={}, games=[]))
        u["n"] += 1; u["hr"] += hr; u["r"] += runs
        p = u["parks"].setdefault(home, [0, 0])
        p[0] += 1; p[1] += hr
        u["games"].append((d, hr))

    out_umps = {}
    for name, u in umps.items():
        if u["n"] < 5:
            continue
        hrpg = u["hr"] / u["n"]
        rpg = u["r"] / u["n"]
        recent = sorted(u["games"])[-5:]
        l5 = sum(h for _, h in recent) / len(recent)
        parks = {code: [p[0], round(p[1] / p[0], 2)]
                 for code, p in u["parks"].items() if p[0] >= 5}
        out_umps[name] = dict(
            n=u["n"], hrpg=round(hrpg, 2),
            vslg=round((hrpg / lg_hrpg - 1) * 100, 1),
            rpg=round(rpg, 2),
            rvslg=round((rpg / lg_rpg - 1) * 100, 1),
            last5=dict(hrpg=round(l5, 2),
                       vscareer=round((l5 / hrpg - 1) * 100, 1) if hrpg else 0,
                       to=recent[-1][0] if recent else None),
            parks=parks)

    # league context / records
    record = max(rows, key=lambda r: r[4])
    qual = {k: v for k, v in out_umps.items() if v["n"] >= 30}
    top = max(qual.items(), key=lambda kv: kv[1]["vslg"]) if qual else None
    low = min(qual.items(), key=lambda kv: kv[1]["vslg"]) if qual else None

    payload = dict(
        built=datetime.now(ET).strftime("%Y-%m-%d %H:%M ET"),
        seasons="2017-2026",
        league=dict(n=total_g, hrpg=round(lg_hrpg, 3), rpg=round(lg_rpg, 2),
                    hrs=total_hr),
        meta=dict(games=total_g, hrs=total_hr, umps=len(out_umps),
                  top=[top[0], top[1]["vslg"]] if top else None,
                  low=[low[0], low[1]["vslg"]] if low else None,
                  record=dict(hr=record[4], d=record[0],
                              matchup=f"{record[2]}@{record[1]}", ump=record[3])),
        umps=out_umps)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(payload, f, separators=(",", ":"))
    print(f"Wrote {OUT}: {len(out_umps)} umps, league {lg_hrpg:.2f} HR/g over {total_g} games")


if __name__ == "__main__":
    main()
