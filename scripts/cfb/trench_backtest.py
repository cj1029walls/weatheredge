#!/usr/bin/env python3
"""CFB TRENCH EDGE — backtest, not a product (yet).

Question under test: does the WEIGHT differential between a team's offensive
line and the opposing defensive line predict anything bettable — rushing
yards, yards per carry, time of possession, covers, unders?

Data: CollegeFootballData.com (CFBD_API_KEY secret, same key the CFB radar
already uses).
  /roster?year=Y            -> every player's listed weight + position
  /games?year=Y             -> FBS results
  /lines?year=Y             -> real spreads & totals (median across books)
  /games/teams?year=Y&week=W-> per-game team box stats (rush yds/att, poss.)

Per team-season: average listed weight of the OL group and DL group.
Per game (FBS vs FBS): each offense's trench diff = own OL avg - opp DL avg.

Outputs data/cfb/trench_backtest.json with:
  * correlation of trench diff vs YPC / rush yards / possession
  * bucketed outcomes by diff (lbs/man): rushing, cover rate, over rate
  * the honest control: does trench diff add anything BEYOND the spread?
    (cover-rate buckets are exactly that test — books already price talent)

Verdict rules printed at the end. No third-party dependencies.
"""
import functools, json, os, statistics, sys, time, urllib.request

print = functools.partial(print, flush=True)

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
OUT = os.path.join(ROOT, "data", "cfb", "trench_backtest.json")

CFBD = "https://api.collegefootballdata.com"
SEASONS = [2021, 2022, 2023, 2024]
OL_POS = {"OL", "OT", "OG", "C", "G", "T"}
DL_POS = {"DL", "DT", "DE", "NT", "EDGE"}


def gv(d, *names):
    for n in names:
        if n in d and d[n] is not None:
            return d[n]
    return None


def fetch(url, tries=4, timeout=90):
    hdrs = {"User-Agent": "dfsradar-build/1.0", "Accept": "application/json",
            "Authorization": f"Bearer {os.environ.get('CFBD_API_KEY','')}"}
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except Exception as e:
            code = getattr(e, "code", None)
            if i == tries - 1:
                raise
            wait = 45 if code == 429 else 8 * (i + 1)
            print(f"    retry {i+1}/{tries} in {wait}s: {e}")
            time.sleep(wait)


def corr(xs, ys):
    n = len(xs)
    if n < 30:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sx = (sum((x - mx) ** 2 for x in xs)) ** 0.5
    sy = (sum((y - my) ** 2 for y in ys)) ** 0.5
    if not sx or not sy:
        return None
    return round(sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy), 3)


def main():
    rows = []          # one row per offense per game
    game_rows = []     # one row per game (net mass, spread, total, results)
    for year in SEASONS:
        print(f"== season {year}")
        fbs = {gv(t, "school") for t in fetch(f"{CFBD}/teams/fbs?year={year}")}
        print(f"  FBS teams: {len(fbs)}")
        # trench weights per team
        roster = fetch(f"{CFBD}/roster?year={year}")
        tw = {}
        for p in roster:
            team = gv(p, "team")
            pos = (gv(p, "position") or "").upper()
            w = gv(p, "weight")
            if not team or not w or not (180 <= w <= 420):
                continue
            grp = "ol" if pos in OL_POS else "dl" if pos in DL_POS else None
            if grp:
                tw.setdefault(team, {"ol": [], "dl": []})[grp].append(w)
        trench = {t: dict(ol=round(statistics.mean(v["ol"]), 1),
                          dl=round(statistics.mean(v["dl"]), 1),
                          nOl=len(v["ol"]), nDl=len(v["dl"]))
                  for t, v in tw.items()
                  if t in fbs and len(v["ol"]) >= 8 and len(v["dl"]) >= 6}
        print(f"  teams with trench data: {len(trench)}")

        # results + lines
        games = fetch(f"{CFBD}/games?year={year}&seasonType=regular")
        lines_raw = fetch(f"{CFBD}/lines?year={year}&seasonType=regular")
        lines = {}
        for L in lines_raw:
            gid = gv(L, "id", "gameId")
            spreads = [gv(x, "spread") for x in (L.get("lines") or [])
                       if gv(x, "spread") is not None]
            totals = [gv(x, "overUnder", "over_under") for x in (L.get("lines") or [])
                      if gv(x, "overUnder", "over_under") is not None]
            if gid and (spreads or totals):
                lines[gid] = dict(
                    spread=(statistics.median(spreads) if spreads else None),
                    total=(statistics.median(totals) if totals else None))
        ginfo = {}
        for g in games:
            hp, ap = gv(g, "homePoints", "home_points"), gv(g, "awayPoints", "away_points")
            if hp is None or ap is None:
                continue
            ginfo[gv(g, "id")] = dict(
                home=gv(g, "homeTeam", "home_team"), away=gv(g, "awayTeam", "away_team"),
                hp=hp, ap=ap)

        # per-game team box stats, week by week
        for week in range(1, 16):
            try:
                wk = fetch(f"{CFBD}/games/teams?year={year}&seasonType=regular&week={week}",
                           tries=2)
            except Exception as e:
                print(f"  week {week}: unavailable ({e})")
                continue
            time.sleep(0.4)
            for g in wk:
                gid = gv(g, "id", "gameId")
                info = ginfo.get(gid)
                if not info:
                    continue
                teams = g.get("teams") or []
                if len(teams) != 2:
                    continue
                per = {}
                for t in teams:
                    school = gv(t, "school", "team")
                    stats = {gv(s, "category"): gv(s, "stat")
                             for s in (t.get("stats") or [])}
                    try:
                        ry = float(stats.get("rushingYards"))
                        ra = float(str(stats.get("rushingAttempts")))
                    except (TypeError, ValueError):
                        continue
                    poss = stats.get("possessionTime")
                    psec = None
                    if isinstance(poss, str) and ":" in poss:
                        try:
                            mm, ss = poss.split(":")
                            psec = int(mm) * 60 + int(ss)
                        except ValueError:
                            pass
                    per[school] = dict(ry=ry, ra=ra, pos=psec,
                                       ha=gv(t, "homeAway", "home_away"))
                if len(per) != 2:
                    continue
                names = list(per)
                for me in names:
                    opp = names[0] if names[1] == me else names[1]
                    tm, to = trench.get(me), trench.get(opp)
                    if not tm or not to or per[me]["ra"] < 15:
                        continue
                    rows.append(dict(
                        y=year, diff=round(tm["ol"] - to["dl"], 1),
                        ry=per[me]["ry"], ra=per[me]["ra"],
                        ypc=round(per[me]["ry"] / per[me]["ra"], 2),
                        pos=per[me]["pos"]))
                # game-level: net mass edge for the HOME team
                h, a = info["home"], info["away"]
                th, ta = trench.get(h), trench.get(a)
                ln = lines.get(gid) or {}
                if th and ta:
                    net = round((th["ol"] + th["dl"]) - (ta["ol"] + ta["dl"]), 1)
                    margin = info["hp"] - info["ap"]
                    cover = None
                    if ln.get("spread") is not None:
                        # CFBD spread is the home line (negative = home favored)
                        adj = margin + ln["spread"]
                        cover = None if adj == 0 else adj > 0
                    over = None
                    if ln.get("total") is not None:
                        tot = info["hp"] + info["ap"]
                        over = None if tot == ln["total"] else tot > ln["total"]
                    game_rows.append(dict(y=year, net=net, margin=margin,
                                          spread=ln.get("spread"),
                                          cover=cover, over=over,
                                          mass=round(th["ol"] + th["dl"] + ta["ol"] + ta["dl"], 0)))
        print(f"  running rows: {len(rows)} offense-games · {len(game_rows)} games")

    # ================= analysis =================
    print(f"\nTOTAL: {len(rows)} offense-games, {len(game_rows)} games\n")
    out = dict(seasons=SEASONS, offenseGames=len(rows), games=len(game_rows))

    out["corr"] = dict(
        diff_vs_ypc=corr([r["diff"] for r in rows], [r["ypc"] for r in rows]),
        diff_vs_rushYds=corr([r["diff"] for r in rows], [r["ry"] for r in rows]),
        diff_vs_possession=corr([r["diff"] for r in rows if r["pos"]],
                                [r["pos"] for r in rows if r["pos"]]))
    print("correlations:", out["corr"])

    # center diff per season: OL groups run ~20 lbs heavier than DL by nature,
    # so the raw diff is positional physiology; the EDGE is distance from the
    # season's mean diff.
    by_year_mean = {}
    for y in SEASONS:
        ys = [r["diff"] for r in rows if r["y"] == y]
        if ys:
            by_year_mean[y] = statistics.mean(ys)
    for r in rows:
        r["cdiff"] = round(r["diff"] - by_year_mean.get(r["y"], 0), 1)
    cds = sorted(r["cdiff"] for r in rows)
    qs = [cds[int(len(cds) * k / 5)] for k in range(1, 5)]
    print(f"\ncentered diff quintile cuts: {qs}")
    def cbucket(lo, hi, label):
        sub = [r for r in rows if lo <= r["cdiff"] < hi]
        if len(sub) < 30:
            return None
        b = dict(label=label, n=len(sub),
                 ypc=round(statistics.mean(r["ypc"] for r in sub), 2),
                 rushYds=round(statistics.mean(r["ry"] for r in sub)))
        print(f"  {label}: n={b['n']} ypc={b['ypc']} rush={b['rushYds']}")
        return b
    print("centered OL-vs-opp-DL edge (quintiles) -> offense output:")
    out["centeredBuckets"] = [b for b in [
        cbucket(-999, qs[0], "Q1 lightest edge"), cbucket(qs[0], qs[1], "Q2"),
        cbucket(qs[1], qs[2], "Q3"), cbucket(qs[2], qs[3], "Q4"),
        cbucket(qs[3], 999, "Q5 heaviest edge")] if b]

    def bucket_off(lo, hi, label):
        sub = [r for r in rows if lo <= r["diff"] < hi]
        if len(sub) < 30:
            return None
        b = dict(label=label, n=len(sub),
                 ypc=round(statistics.mean(r["ypc"] for r in sub), 2),
                 rushYds=round(statistics.mean(r["ry"] for r in sub)),
                 possMin=round(statistics.mean(r["pos"] for r in sub if r["pos"]) / 60, 1)
                 if any(r["pos"] for r in sub) else None)
        print(f"  {label}: n={b['n']} ypc={b['ypc']} rush={b['rushYds']} poss={b['possMin']}m")
        return b
    print("\nOL-vs-DL weight diff (lbs/man) -> offense output:")
    out["offBuckets"] = [b for b in [
        bucket_off(-99, -15, "diff <= -15"), bucket_off(-15, -5, "-15..-5"),
        bucket_off(-5, 5, "-5..+5"), bucket_off(5, 15, "+5..+15"),
        bucket_off(15, 99, "diff >= +15")] if b]

    def bucket_ats(lo, hi, label):
        sub = [g for g in game_rows if lo <= g["net"] < hi and g["cover"] is not None]
        if len(sub) < 30:
            return None
        w = sum(1 for g in sub if g["cover"])
        sp = [g for g in game_rows if lo <= g["net"] < hi and g["spread"] is not None]
        b = dict(label=label, n=len(sub), coverPct=round(100 * w / len(sub), 1),
                 avgSpread=round(statistics.mean(g["spread"] for g in sp), 1),
                 avgMargin=round(statistics.mean(g["margin"] for g in sub), 1))
        print(f"  {label}: n={b['n']} home covers {b['coverPct']}% "
              f"(avg spread {b['avgSpread']}, avg margin {b['avgMargin']})")
        return b
    print("\nHOME net trench mass edge (lbs across OL+DL avgs) -> ATS:")
    out["atsBuckets"] = [b for b in [
        bucket_ats(-999, -30, "net <= -30"), bucket_ats(-30, -10, "-30..-10"),
        bucket_ats(-10, 10, "-10..+10"), bucket_ats(10, 30, "+10..+30"),
        bucket_ats(30, 999, "net >= +30")] if b]

    def bucket_total(lo, hi, label):
        sub = [g for g in game_rows if lo <= g["mass"] < hi and g["over"] is not None]
        if len(sub) < 30:
            return None
        w = sum(1 for g in sub if g["over"])
        b = dict(label=label, n=len(sub), overPct=round(100 * w / len(sub), 1))
        print(f"  {label}: n={b['n']} overs {b['overPct']}%")
        return b
    masses = sorted(g["mass"] for g in game_rows if g["over"] is not None)
    if masses:
        q1, q3 = masses[len(masses)//4], masses[3*len(masses)//4]
        print(f"\nCombined game mass (both teams' trench avgs) -> totals "
              f"(quartiles {q1}/{q3}):")
        out["totalBuckets"] = [b for b in [
            bucket_total(0, q1, f"light (<{q1})"),
            bucket_total(q1, q3, "middle"),
            bucket_total(q3, 9999, f"heavy (>={q3})")] if b]

    # per-season stability of the positive-edge ATS signal
    stab = []
    for y in SEASONS:
        sub = [g for g in game_rows if g["y"] == y and g["net"] >= 10 and g["cover"] is not None]
        neg = [g for g in game_rows if g["y"] == y and g["net"] <= -10 and g["cover"] is not None]
        if sub:
            stab.append(dict(y=y, posN=len(sub),
                posCover=round(100 * sum(1 for g in sub if g["cover"]) / len(sub), 1),
                negN=len(neg),
                negCover=(round(100 * sum(1 for g in neg if g["cover"]) / len(neg), 1) if neg else None)))
    out["atsBySeason"] = stab
    print("\nATS stability by season (net>=+10 home cover% / net<=-10):")
    for r2 in stab:
        print(f"  {r2['y']}: heavy-home {r2['posCover']}% (n={r2['posN']}) · light-home {r2['negCover']}% (n={r2['negN']})")

    # spread-vs-mass control: how much of the mass edge is already priced?
    sp_rows = [g for g in game_rows if g["spread"] is not None]
    out["massVsSpread"] = corr([g["net"] for g in sp_rows],
                               [-g["spread"] for g in sp_rows])
    print(f"\ncontrol: net mass vs (negated) spread correlation: {out['massVsSpread']}"
          f"  (high = books already price the trenches)")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w"), separators=(",", ":"))
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
