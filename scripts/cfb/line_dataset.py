#!/usr/bin/env python3
"""CFB line-play dataset for the trench rebuild (research input, not a page).

One row per FBS-vs-FBS team-game, 2019 and 2021-2026: the box-score rushing
line (attempts, yards) and CollegeFootballData's line-play stats for that
offense in that game (line yards, stuff rate, power success, second-level and
open-field yards, rushing success rate and PPA). The opponent's row is the
same game from the other side, so "what this defense allowed" needs no extra
columns. Also: each team-season's average listed OL and DL weight, so the old
weight edge can be scored on exactly the same games.

About 31 CFBD calls a season (games, 15 weeks of box scores, 15 weeks of
advanced stats, roster): ~220 in all. Finished seasons never change, so this
is a one-off and does not go through the committed cache.

Outputs: data/cfb/line_games.csv.gz, data/cfb/line_weights.json
"""
import csv, gzip, io, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
OUT = os.path.join(ROOT, "data", "cfb", "line_games.csv.gz")
WOUT = os.path.join(ROOT, "data", "cfb", "line_weights.json")
BASE = "https://api.collegefootballdata.com"
SEASONS = [2019, 2021, 2022, 2023, 2024, 2025, 2026]
OL = {"OL", "OT", "OG", "C", "G", "T"}
DL = {"DL", "DT", "DE", "NT", "EDGE"}
KEY = re.sub(r"\s+", "", os.environ.get("CFBD_API_KEY", ""))
COLS = ["season", "week", "gid", "team", "opp", "home", "neutral", "att", "yds", "passYds",
        "ly", "lyTot", "stuff", "power", "sec", "open", "rSR", "rPPA", "rExp", "sr", "ppa", "plays"]
STATE = {"calls": 0, "left": None}


def get(path, **params):
    url = BASE + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "Accept": "application/json", "User-Agent": "dfsradar-research/1.0",
        "Authorization": f"Bearer {KEY}"})
    for attempt in (1, 2):
        STATE["calls"] += 1
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                STATE["left"] = r.headers.get("X-CallLimit-Remaining") or STATE["left"]
                time.sleep(0.3)
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 429) or attempt == 2:      # a quota refusal is never retried
                sys.exit(f"::error::CFBD refused {path} {params}: HTTP {e.code}")
        except Exception as e:
            if attempt == 2:
                sys.exit(f"::error::CFBD unreachable for {path} {params}: {e}")
        time.sleep(5)


def g(d, *names):
    for n in names:
        if isinstance(d, dict) and d.get(n) is not None:
            return d[n]
    return None


def main():
    if not KEY:
        sys.exit("::error::CFBD_API_KEY is not set")
    rows, weights, shown = [], {}, False
    for y in SEASONS:
        fbs = {}
        for gm in get("/games", year=y, seasonType="regular"):
            hc = str(g(gm, "homeClassification", "home_classification", "home_division") or "").lower()
            ac = str(g(gm, "awayClassification", "away_classification", "away_division") or "").lower()
            if hc == "fbs" and ac == "fbs" and g(gm, "completed"):
                fbs[g(gm, "id")] = (g(gm, "week"), g(gm, "homeTeam", "home_team"),
                                    g(gm, "awayTeam", "away_team"),
                                    1 if g(gm, "neutralSite", "neutral_site") else 0)
        n0 = len(rows)
        for w in sorted({v[0] for v in fbs.values()}):
            box = get("/games/teams", year=y, week=w, seasonType="regular")
            adv = get("/stats/game/advanced", year=y, week=w, seasonType="regular")
            if adv and not shown:
                shown = True
                print("advanced row keys:", sorted(adv[0].keys()),
                      "| offense keys:", sorted((g(adv[0], "offense") or {}).keys()))
            off = {(g(a, "gameId", "game_id"), g(a, "team")): g(a, "offense") or {} for a in adv}
            for b in box:
                gid = g(b, "id", "gameId", "game_id")
                if gid not in fbs:
                    continue
                _, home, away, neutral = fbs[gid]
                for t in b.get("teams") or []:
                    name = g(t, "team", "school")
                    st = {s.get("category"): s.get("stat") for s in (t.get("stats") or [])}
                    o = off.get((gid, name)) or {}
                    rp = g(o, "rushingPlays", "rushing_plays") or {}
                    rows.append([
                        y, w, gid, name, away if name == home else home,
                        1 if name == home else 0, neutral,
                        st.get("rushingAttempts"), st.get("rushingYards"), st.get("netPassingYards"),
                        g(o, "lineYards", "line_yards"), g(o, "lineYardsTotal", "line_yards_total"),
                        g(o, "stuffRate", "stuff_rate"), g(o, "powerSuccess", "power_success"),
                        g(o, "secondLevelYards", "second_level_yards"),
                        g(o, "openFieldYards", "open_field_yards"),
                        g(rp, "successRate", "success_rate"), g(rp, "ppa"), g(rp, "explosiveness"),
                        g(o, "successRate", "success_rate"), g(o, "ppa"), g(o, "plays")])
        byteam = {}
        for p in get("/roster", year=y):
            pos, wt, tm = str(g(p, "position") or "").upper(), g(p, "weight"), g(p, "team", "school")
            k = "ol" if pos in OL else "dl" if pos in DL else None
            if tm and k and wt and wt >= 150:
                byteam.setdefault(tm, {"ol": [], "dl": []})[k].append(wt)
        weights[str(y)] = {tm: [round(sum(v["ol"]) / len(v["ol"]), 1) if v["ol"] else None,
                                round(sum(v["dl"]) / len(v["dl"]), 1) if v["dl"] else None,
                                len(v["ol"]), len(v["dl"])] for tm, v in byteam.items()}
        print(f"{y}: {len(fbs)} FBS games, {len(rows) - n0} team-games, "
              f"{STATE['calls']} calls so far, {STATE['left']} left this month")

    buf = io.StringIO()
    wr = csv.writer(buf, lineterminator="\n")
    wr.writerow(COLS)
    wr.writerows(rows)
    with open(OUT, "wb") as f:
        f.write(gzip.compress(buf.getvalue().encode(), 9, mtime=0))
    with open(WOUT, "w") as f:
        json.dump(weights, f, separators=(",", ":"), sort_keys=True)
    filled = sum(1 for r in rows if r[10] is not None)
    print(f"wrote {len(rows)} team-games ({filled} with line-play stats) — "
          f"{STATE['calls']} CFBD calls, {STATE['left']} left this month")
    if not rows or filled < len(rows) * 0.8:
        sys.exit("::error::line-play stats are missing for most games — check the field names printed above")


if __name__ == "__main__":
    main()
