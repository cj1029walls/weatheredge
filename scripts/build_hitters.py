#!/usr/bin/env python3
"""Build the hitter game-log history joined to park weather.

For every position player on every team's active roster, pull the last three
seasons of hitting game logs from the MLB Stats API and join each game to the
first-pitch weather already in data/parks_history.json (same park+date join
the pitcher feature uses).

Output: data/hitters_history.json
  { "<TEAM>": { "players": { "<pid>": { "name": ..., "g": [[t,w,ab,tb,hr],...] } } },
    "_built": "YYYY-MM-DD", "_seasons": [..] }

Game row: t=temp°F, w=wind mph, ab=at-bats, tb=total bases, hr=home runs.

~1,200 API calls — runs weekly via .github/workflows/build-hitters.yml.
No third-party dependencies.
"""
import functools, json, os, sys, time, urllib.request
from datetime import date

sys.path.insert(0, os.path.dirname(__file__))
from parks import PARKS, MLBID_TO_CODE

print = functools.partial(print, flush=True)   # live logs on CI

ROOT = os.path.join(os.path.dirname(__file__), "..")
OUT = os.path.join(ROOT, "data", "hitters_history.json")
HISTORY = os.path.join(ROOT, "data", "parks_history.json")

ROSTER_URL = "https://statsapi.mlb.com/api/v1/teams/{tid}/roster?rosterType=active"
GAMELOG_URL = ("https://statsapi.mlb.com/api/v1/people/{pid}/stats"
               "?stats=gameLog&group=hitting&season={season}")
SEASONS = [date.today().year - 2, date.today().year - 1, date.today().year]


def get_json(url, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "weatheredge-build/1.0"})
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read())
        except Exception as e:
            if i == tries - 1:
                raise
            print(f"    retry {i+1}/{tries}: {e}")
            time.sleep(6 * (i + 1))


def main():
    if not os.path.exists(HISTORY):
        sys.exit("data/parks_history.json missing — run the 'Build history' workflow first.")
    hist = json.load(open(HISTORY))

    # index first-pitch weather by (park, yyyymmdd) once
    wx = {}
    for code, blob in hist.items():
        if code.startswith("_"):
            continue
        for g in blob["games"]:
            wx[(code, g["d"])] = (g["t"], g["w"])
    print(f"Weather index: {len(wx)} park-days")

    out = {}
    total_players = 0
    for code, meta in sorted(PARKS.items()):
        try:
            roster = get_json(ROSTER_URL.format(tid=meta["mlbid"]))
        except Exception as e:
            print(f"  {code}: roster unavailable ({e}) — skipping team")
            out[code] = dict(players={})
            continue
        hitters = [r for r in roster.get("roster", [])
                   if r.get("position", {}).get("abbreviation") not in ("P", None)]
        players = {}
        for r in hitters:
            pid = r["person"]["id"]
            name = r["person"]["fullName"]
            rows = []
            for season in SEASONS:
                try:
                    data = get_json(GAMELOG_URL.format(pid=pid, season=season), tries=2)
                except Exception as e:
                    print(f"    {name} {season}: {e}")
                    continue
                stats = data.get("stats") or [{}]
                for s in stats[0].get("splits", []):
                    st = s.get("stat", {})
                    ab = st.get("atBats", 0) or 0
                    if not ab:
                        continue
                    side = s.get("team") if s.get("isHome") else (s.get("opponent") or {})
                    pcode = MLBID_TO_CODE.get((side or {}).get("id"))
                    d = (s.get("date") or "").replace("-", "")
                    w = wx.get((pcode, d))
                    if not w:
                        continue
                    h = st.get("hits", 0) or 0
                    d2 = st.get("doubles", 0) or 0
                    d3 = st.get("triples", 0) or 0
                    hr = st.get("homeRuns", 0) or 0
                    tb = h + d2 + 2 * d3 + 3 * hr
                    rows.append([w[0], w[1], ab, tb, hr])
                time.sleep(0.25)
            if rows:
                players[str(pid)] = dict(name=name, g=rows)
        out[code] = dict(players=players)
        total_players += len(players)
        print(f"  {code}: {len(players)} hitters with weather-joined games")

    out["_built"] = date.today().isoformat()
    out["_seasons"] = SEASONS
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(out, f, separators=(",", ":"))
    print(f"Wrote {OUT} — {total_players} hitters across {len(PARKS)} teams")


if __name__ == "__main__":
    main()
