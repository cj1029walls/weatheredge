#!/usr/bin/env python3
"""DFSRADAR NFL — deep situational history (the NFL "edge layer").

Tier 1 — from the nflverse games file (works everywhere, incl. CI):
  * REFEREE crews: points/game vs league, over rate vs the closing total,
    home cover rate vs the closing spread (penalties joined from tier 2)
  * TRAVEL / CIRCADIAN spots: west-coast teams in early-ET windows,
    west teams at night, cross-country trips — ATS + totals records
  * REST edges: short weeks (Thu), off the bye, big rest mismatches
  * TEAM WEATHER IDENTITY: each team's scoring in cold / wind / heat bands
    vs its own baseline ("MIA under 40°" lives here)
  * QB starts proxy: team scoring in each QB's cold/windy starts

Tier 2 — from nflverse play-by-play releases (Actions only; guarded):
  * penalties + penalty yards per referee crew
  * KICKER splits: FG% by wind / cold / distance / Denver altitude
  * QB passing splits: yards, TD, comp% in cold / windy vs baseline

Output: data/nfl/deep.json  (committed; consumed by the NFL page + PRO)
No third-party dependencies.
"""
import csv, functools, gzip, io, json, os, sys, time, urllib.request
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(__file__))
from stadiums import STADIUMS

print = functools.partial(print, flush=True)

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
OUT = os.path.join(ROOT, "data", "nfl", "deep.json")

GAMES_URL = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
PBP_URL = ("https://github.com/nflverse/nflverse-data/releases/download/pbp/"
           "play_by_play_{y}.csv.gz")
SEASONS = list(range(2015, 2026))
ET = timezone(timedelta(hours=-5))

TZ_OFF = {"America/New_York": -5, "America/Detroit": -5, "America/Chicago": -6,
          "America/Denver": -7, "America/Phoenix": -7, "America/Los_Angeles": -8}
TEAM_FIX = {"OAK": "LV", "SD": "LAC", "STL": "LA", "LAR": "LA"}

COLD, CHILLY, HOT, WINDY = 40, 55, 85, 15


def fetch(url, timeout=120):
    req = urllib.request.Request(url, headers={"User-Agent": "dfsradar-nfl/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def team_tz(team):
    s = STADIUMS.get(team)
    return TZ_OFF.get(s["tz"], -5) if s else -5


def rec(d, key):
    return d.setdefault(key, {"n": 0, "atsW": 0, "atsL": 0, "overW": 0,
                              "overL": 0, "pts": 0.0})


def load_games():
    rows = list(csv.DictReader(io.StringIO(fetch(GAMES_URL).decode("utf-8"))))
    out = []
    for r in rows:
        try:
            season = int(r["season"])
        except ValueError:
            continue
        if season not in SEASONS or r.get("game_type") != "REG":
            continue
        if not r.get("home_score") or not r.get("away_score"):
            continue
        away = TEAM_FIX.get(r["away_team"], r["away_team"])
        home = TEAM_FIX.get(r["home_team"], r["home_team"])
        g = dict(
            id=r["game_id"], season=season,
            away=away, home=home,
            away_pts=int(r["away_score"]), home_pts=int(r["home_score"]),
            total=int(r["away_score"]) + int(r["home_score"]),
            line=float(r["total_line"]) if r.get("total_line") else None,
            spread=float(r["spread_line"]) if r.get("spread_line") else None,
            ref=(r.get("referee") or "").strip() or None,
            away_rest=int(r["away_rest"]) if r.get("away_rest") else None,
            home_rest=int(r["home_rest"]) if r.get("home_rest") else None,
            roof=(r.get("roof") or "").lower(),
            surface=(r.get("surface") or "").lower(),
            temp=int(r["temp"]) if r.get("temp") else None,
            wind=int(r["wind"]) if r.get("wind") else None,
            time=r.get("gametime") or "",
            neutral=(r.get("location") or "") == "Neutral",
            away_qb=r.get("away_qb_name") or None,
            home_qb=r.get("home_qb_name") or None)
        g["outdoor"] = g["roof"] in ("outdoors", "open")
        g["result"] = g["home_pts"] - g["away_pts"]        # home margin
        out.append(g)
    print(f"games loaded: {len(out)} REG {SEASONS[0]}-{SEASONS[-1]}")
    return out


def ats(g, side):
    """Did `side` cover the closing spread? spread_line >0 = home favored."""
    if g["spread"] is None or g["result"] == g["spread"]:
        return None
    home_cov = g["result"] > g["spread"]
    return home_cov if side == "home" else not home_cov


def over(g):
    if g["line"] is None or g["total"] == g["line"]:
        return None
    return g["total"] > g["line"]


def add_spot(d, key, g, side):
    e = rec(d, key)
    a = ats(g, side)
    o = over(g)
    e["n"] += 1
    e["pts"] += g["total"]
    if a is True: e["atsW"] += 1
    elif a is False: e["atsL"] += 1
    if o is True: e["overW"] += 1
    elif o is False: e["overL"] += 1


def build_tier1(games):
    league_pts = sum(g["total"] for g in games) / len(games)
    # ---- referees ----
    refs_raw = {}
    for g in games:
        if not g["ref"]:
            continue
        e = refs_raw.setdefault(g["ref"], dict(n=0, pts=0.0, ow=0, ol=0,
                                               hcw=0, hcl=0, hw=0))
        e["n"] += 1
        e["pts"] += g["total"]
        o = over(g)
        if o is True: e["ow"] += 1
        elif o is False: e["ol"] += 1
        a = ats(g, "home")
        if a is True: e["hcw"] += 1
        elif a is False: e["hcl"] += 1
        if g["result"] > 0: e["hw"] += 1
    refs = {}
    for name, e in refs_raw.items():
        if e["n"] < 30:
            continue
        ppg = e["pts"] / e["n"]
        refs[name] = dict(
            n=e["n"], ppg=round(ppg, 1),
            vslg=round((ppg / league_pts - 1) * 100, 1),
            overPct=round(100 * e["ow"] / (e["ow"] + e["ol"])) if e["ow"] + e["ol"] else None,
            homeCoverPct=round(100 * e["hcw"] / (e["hcw"] + e["hcl"])) if e["hcw"] + e["hcl"] else None,
            homeWinPct=round(100 * e["hw"] / e["n"]))
    # ---- travel / circadian / rest spots ----
    spots, team_spots = {}, {}
    for g in games:
        if g["neutral"]:
            continue
        a_tz, h_tz = team_tz(g["away"]), team_tz(g["home"])
        shift = h_tz - a_tz                       # negative = traveling west
        try:
            kick_et = int(g["time"].split(":")[0])
        except (ValueError, AttributeError, IndexError):
            kick_et = 13
        body_clock = kick_et + (a_tz - (-5))      # away team's body-clock hour
        # west-coast (PT/MT) team in an early ET window — body clock ~10 AM
        if a_tz <= -7 and kick_et <= 13:
            add_spot(spots, "westEarly", g, "away")
            add_spot(team_spots.setdefault(g["away"], {}), "westEarly", g, "away")
        # west team playing at night (circadian peak) anywhere east
        if a_tz <= -7 and kick_et >= 20:
            add_spot(spots, "westNight", g, "away")
        # eastern team traveling 2+ zones west
        if a_tz == -5 and shift <= -2:
            add_spot(spots, "eastWest", g, "away")
            add_spot(team_spots.setdefault(g["away"], {}), "eastWest", g, "away")
        # rest
        if g["away_rest"] is not None and g["home_rest"] is not None:
            if g["away_rest"] <= 5:
                add_spot(spots, "shortWeekAway", g, "away")
            if g["home_rest"] <= 5:
                add_spot(spots, "shortWeekHome", g, "home")
            if g["away_rest"] >= 13:
                add_spot(spots, "offByeAway", g, "away")
            if g["away_rest"] - g["home_rest"] >= 4:
                add_spot(spots, "restEdgeAway", g, "away")
            if g["home_rest"] - g["away_rest"] >= 4:
                add_spot(spots, "restEdgeHome", g, "home")
    def finish(d):
        out = {}
        for k, e in d.items():
            if e["n"] < 8 and d is not spots:
                continue
            out[k] = dict(n=e["n"], atsW=e["atsW"], atsL=e["atsL"],
                          overW=e["overW"], overL=e["overL"],
                          avgPts=round(e["pts"] / e["n"], 1))
        return out
    situations = dict(league=finish(spots),
                      teams={t: finish(d) for t, d in team_spots.items()
                             if finish(d)})
    # ---- team weather identity (outdoor games with recorded temp) ----
    team_wx = {}
    for g in games:
        if not g["outdoor"] or g["temp"] is None:
            continue
        for team, pts in ((g["away"], g["away_pts"]), (g["home"], g["home_pts"])):
            e = team_wx.setdefault(team, dict(all=[0, 0], cold=[0, 0],
                                              chilly=[0, 0], hot=[0, 0],
                                              windy=[0, 0]))
            e["all"][0] += 1; e["all"][1] += pts
            if g["temp"] < COLD: e["cold"][0] += 1; e["cold"][1] += pts
            elif g["temp"] < CHILLY: e["chilly"][0] += 1; e["chilly"][1] += pts
            if g["temp"] >= HOT: e["hot"][0] += 1; e["hot"][1] += pts
            if (g["wind"] or 0) >= WINDY: e["windy"][0] += 1; e["windy"][1] += pts
    teamWx = {}
    for t, e in team_wx.items():
        if e["all"][0] < 30:
            continue
        base = e["all"][1] / e["all"][0]
        row = dict(basePpg=round(base, 1), n=e["all"][0])
        for band in ("cold", "chilly", "hot", "windy"):
            n, pts = e[band]
            if n >= 5:
                ppg = pts / n
                row[band] = dict(n=n, ppg=round(ppg, 1),
                                 delta=round((ppg / base - 1) * 100))
        teamWx[t] = row
    # ---- QB starts proxy: team scoring in each QB's cold / windy starts ----
    qb_proxy = {}
    for g in games:
        if not g["outdoor"] or g["temp"] is None:
            continue
        for qb, pts in ((g["away_qb"], g["away_pts"]), (g["home_qb"], g["home_pts"])):
            if not qb:
                continue
            e = qb_proxy.setdefault(qb, dict(all=[0, 0], cold=[0, 0], windy=[0, 0]))
            e["all"][0] += 1; e["all"][1] += pts
            if g["temp"] < COLD: e["cold"][0] += 1; e["cold"][1] += pts
            if (g["wind"] or 0) >= WINDY: e["windy"][0] += 1; e["windy"][1] += pts
    qbs_proxy = {}
    for qb, e in qb_proxy.items():
        if e["all"][0] < 12:
            continue
        base = e["all"][1] / e["all"][0]
        row = dict(starts=e["all"][0], teamPpg=round(base, 1))
        for band in ("cold", "windy"):
            n, pts = e[band]
            if n >= 3:
                row[band] = dict(n=n, teamPpg=round(pts / n, 1),
                                 delta=round((pts / n / base - 1) * 100))
        if "cold" in row or "windy" in row:
            qbs_proxy[qb] = row
    return dict(league=dict(n=len(games), ppg=round(league_pts, 1)),
                refs=refs, situations=situations, teamWx=teamWx,
                qbProxy=qbs_proxy)


# ---------------------------------------------------------------- tier 2

def build_tier2(games):
    """Play-by-play: penalties per ref, kicker splits, QB passing splits.
    Heavy downloads — runs on Actions; each season guarded independently."""
    by_id = {g["id"]: g for g in games}
    pen_by_game = {}
    kickers = {}
    qbs = {}
    seasons_ok = []
    for y in SEASONS:
        try:
            raw = fetch(PBP_URL.format(y=y), timeout=300)
        except Exception as e:
            print(f"  pbp {y}: unavailable ({e}) — skipping")
            continue
        try:
            f = io.TextIOWrapper(gzip.GzipFile(fileobj=io.BytesIO(raw)),
                                 encoding="utf-8", errors="replace")
            rd = csv.reader(f)
            hdr = {c: i for i, c in enumerate(next(rd))}
            def col(row, name):
                i = hdr.get(name)
                return row[i] if i is not None and i < len(row) else ""
            n_plays = 0
            for row in rd:
                n_plays += 1
                gid = col(row, "game_id")
                g = by_id.get(gid)
                if g is None:
                    continue
                # penalties
                if col(row, "penalty") == "1":
                    e = pen_by_game.setdefault(gid, [0, 0.0])
                    e[0] += 1
                    try:
                        e[1] += float(col(row, "penalty_yards") or 0)
                    except ValueError:
                        pass
                # kickers
                if col(row, "play_type") == "field_goal":
                    nm = col(row, "kicker_player_name")
                    res = col(row, "field_goal_result")
                    try:
                        dist = int(float(col(row, "kick_distance")))
                    except ValueError:
                        dist = None
                    if nm and res in ("made", "missed", "blocked") and dist:
                        k = kickers.setdefault(nm, dict(seasons=set(), att=[]))
                        k["seasons"].add(y)
                        k["att"].append((dist, res == "made",
                                         g["temp"], g["wind"],
                                         g["outdoor"], g["home"]))
                # QB passing (per game aggregation)
                nm = col(row, "passer_player_name")
                if nm:
                    q = qbs.setdefault(nm, {}).setdefault(
                        gid, dict(att=0, comp=0, yds=0.0, td=0, i=0, sk=0))
                    if col(row, "sack") == "1":
                        q["sk"] += 1
                    else:
                        cp = col(row, "complete_pass") == "1"
                        ic = col(row, "incomplete_pass") == "1"
                        it = col(row, "interception") == "1"
                        if cp or ic or it:
                            q["att"] += 1
                        if cp:
                            q["comp"] += 1
                            try:
                                q["yds"] += float(col(row, "passing_yards") or 0)
                            except ValueError:
                                pass
                        if col(row, "pass_touchdown") == "1":
                            q["td"] += 1
                        if it:
                            q["i"] += 1
            seasons_ok.append(y)
            print(f"  pbp {y}: {n_plays} plays")
        except Exception as e:
            print(f"  pbp {y}: parse failed ({e}) — skipping")
        time.sleep(1)
    if not seasons_ok:
        return None
    # penalties -> refs
    ref_pen = {}
    for gid, (pen, yds) in pen_by_game.items():
        g = by_id.get(gid)
        if g and g["ref"]:
            e = ref_pen.setdefault(g["ref"], [0, 0, 0.0])
            e[0] += 1; e[1] += pen; e[2] += yds
    refs_pen = {name: dict(n=e[0], penG=round(e[1] / e[0], 1),
                           penYdsG=round(e[2] / e[0], 1))
                for name, e in ref_pen.items() if e[0] >= 20}
    # kicker splits (active in the last two completed seasons)
    recent = {SEASONS[-1], SEASONS[-2]}
    kick_out = {}
    def kd(dst):
        return dict(att=0, made=0) if dst is None else dst
    for nm, k in kickers.items():
        if not (k["seasons"] & recent) or len(k["att"]) < 40:
            continue
        bands = {b: dict(att=0, made=0) for b in
                 ("all", "calm", "windy", "cold", "altitude", "long50", "long50windy")}
        for dist, made, temp, wind, outdoor, home in k["att"]:
            def hit(b):
                bands[b]["att"] += 1
                if made:
                    bands[b]["made"] += 1
            hit("all")
            if outdoor:
                if (wind or 0) >= WINDY: hit("windy")
                elif (wind or 0) < 10: hit("calm")
                if temp is not None and temp < COLD: hit("cold")
                if home == "DEN": hit("altitude")
                if dist >= 50:
                    hit("long50")
                    if (wind or 0) >= WINDY: hit("long50windy")
            elif dist >= 50:
                hit("long50")
        out = {}
        for b, e in bands.items():
            if e["att"] >= (3 if b in ("altitude", "long50windy") else 8):
                out[b] = dict(att=e["att"], made=e["made"],
                              pct=round(100 * e["made"] / e["att"]))
        if len(out) > 1:
            kick_out[nm] = out
    # QB weather splits (active recently, real passing stats)
    qb_out = {}
    for nm, by_game in qbs.items():
        rows = []
        for gid, q in by_game.items():
            g = by_id.get(gid)
            if g is None or q["att"] < 12:
                continue
            rows.append((g, q))
        if len(rows) < 16:
            continue
        if not any(g["season"] >= SEASONS[-2] for g, _ in rows):
            continue
        def agg(rs):
            n = len(rs)
            att = sum(q["att"] for _, q in rs)
            comp = sum(q["comp"] for _, q in rs)
            return dict(g=n, ypg=round(sum(q["yds"] for _, q in rs) / n, 1),
                        ypa=round(sum(q["yds"] for _, q in rs) / att, 2) if att else None,
                        compPct=round(100 * comp / att, 1) if att else None,
                        tdG=round(sum(q["td"] for _, q in rs) / n, 2),
                        intG=round(sum(q["i"] for _, q in rs) / n, 2),
                        skG=round(sum(q["sk"] for _, q in rs) / n, 2))
        base = agg(rows)
        cold = [(g, q) for g, q in rows if g["outdoor"] and g["temp"] is not None and g["temp"] < COLD]
        windy = [(g, q) for g, q in rows if g["outdoor"] and (g["wind"] or 0) >= WINDY]
        entry = dict(base=base)
        if len(cold) >= 3:
            entry["cold"] = agg(cold)
            entry["cold"]["delta"] = round((entry["cold"]["ypg"] / base["ypg"] - 1) * 100)
        if len(windy) >= 3:
            entry["windy"] = agg(windy)
            entry["windy"]["delta"] = round((entry["windy"]["ypg"] / base["ypg"] - 1) * 100)
        if "cold" in entry or "windy" in entry:
            qb_out[nm] = entry
    return dict(seasons=seasons_ok, refsPen=refs_pen,
                kickers=kick_out, qbs=qb_out)


def main():
    games = load_games()
    t1 = build_tier1(games)
    t2 = build_tier2(games)
    if t2:
        for name, extra in t2["refsPen"].items():
            if name in t1["refs"]:
                t1["refs"][name].update(penG=extra["penG"],
                                        penYdsG=extra["penYdsG"])
        t1["kickers"] = t2["kickers"]
        t1["qbs"] = t2["qbs"]
        t1["pbpSeasons"] = t2["seasons"]
        print(f"tier2: {len(t2['kickers'])} kickers, {len(t2['qbs'])} QBs, "
              f"{len(t2['refsPen'])} refs with penalty data")
    else:
        print("tier2 skipped (pbp unreachable) — tier1 only")
    t1["built"] = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    t1["seasonsGames"] = f"{SEASONS[0]}-{SEASONS[-1]}"
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(t1, f, separators=(",", ":"))
    print(f"Wrote {OUT}: {len(t1['refs'])} refs, "
          f"{len(t1['teamWx'])} team wx identities, "
          f"{len(t1['qbProxy'])} QB proxies, "
          f"{len(t1['situations']['league'])} league spots")


if __name__ == "__main__":
    main()
