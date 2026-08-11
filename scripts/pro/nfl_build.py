#!/usr/bin/env python3
"""DFSRADAR PRO — NFL weekly board -> site/pro/nfl.json.

Builds the upcoming week's PRO slate: every game with its line, situational
edge block (refs, travel/rest, team weather identity, QB/kicker splits from
data/nfl/deep.json), plus PROP LEANS priced against The Odds API when player
prop markets are available.

Week selection: games in the next 10 days that haven't been played; if none
(offseason / early week), falls forward to the next scheduled week so the
board always shows the real upcoming slate with real posted lines.

Forecast weather (when kickoffs are inside the 16-day window) is read from
site/nfl/data.json — built by scripts/nfl/weekly_build.py in the same
workflow run — so this script never re-hits the weather API.

Lean rules (all display historical records, never guarantees):
  QB WIND   — forecast wind 15+ and QB's windy split shows real decay
              (ypg delta <= -8%, 5+ game sample)  -> pass yds UNDER lean
  KICKER    — forecast wind 15+ and kicker <=75% in wind (8+ att), or
              Denver altitude book, or cold-game decay -> kicking pts lean
  REF TOTAL — crew overPct >= 57 or <= 43 across 80+ games -> total lean
  SPOT      — WEST AT NIGHT (unders 64-43 since 2015), BODY CLOCK with a
              team-specific record, CROSS-COUNTRY
  COLD      — team scores 8%+ under its norm in sub-40 games (10+ sample)
              and kickoff forecast is sub-40 -> team total under lean

Odds API props (guarded — market keys can change; override with env
ODDS_NFL_PROP_MARKETS, default "player_pass_yds,player_kicking_points").
Each lean that matches a live prop line carries the posted line + price.

Grading: predictions archived to data/pro/nfl_predictions/{season}-w{week}.json
so the grader (built when Week 1 results exist) can score every lean publicly.

No third-party dependencies.
"""
import functools, json, os, re, statistics, sys, unicodedata
import urllib.request
from datetime import datetime, timedelta

print = functools.partial(print, flush=True)

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.join(ROOT, "scripts", "nfl"))
import weekly_build as WB                      # build_edge, GAMES_URL, get_json, ET
from stadiums import STADIUMS

DEEP = os.path.join(ROOT, "data", "nfl", "deep.json")
FREE_DATA = os.path.join(ROOT, "site", "nfl", "data.json")
OUT = os.path.join(ROOT, "site", "pro", "nfl.json")
ARCHIVE_DIR = os.path.join(ROOT, "data", "pro", "nfl_predictions")

PROP_MARKETS = os.environ.get("ODDS_NFL_PROP_MARKETS",
                              "player_pass_yds,player_kicking_points")
EVENTS_URL = ("https://api.the-odds-api.com/v4/sports/americanfootball_nfl/events"
              "?apiKey={key}")
EVENT_ODDS_URL = ("https://api.the-odds-api.com/v4/sports/americanfootball_nfl/"
                  "events/{eid}/odds?apiKey={key}&regions=us&markets={mkts}"
                  "&oddsFormat=american")


# ---------------------------------------------------------------- schedule
def load_week():
    """All rows for the target week: next-10-day games, else next scheduled week."""
    raw = urllib.request.urlopen(
        urllib.request.Request(WB.GAMES_URL, headers={"User-Agent": "dfsradar-build/1.0"}),
        timeout=90).read()
    import csv, io
    rows = list(csv.DictReader(io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8")))
    today = datetime.now(WB.ET).date()

    def gdate(r):
        try:
            return datetime.strptime(r.get("gameday") or "", "%Y-%m-%d").date()
        except ValueError:
            return None

    future = [r for r in rows if not r.get("home_score")
              and (d := gdate(r)) and d >= today]
    if not future:
        return [], None, None
    near = [r for r in future if gdate(r) <= today + timedelta(days=10)]
    pool = near or future
    # lock to a single (season, week): the earliest one in the pool
    first = min(pool, key=gdate)
    season, week = first.get("season"), first.get("week")
    wk = [r for r in future if r.get("season") == season and r.get("week") == week]
    wk.sort(key=lambda r: (r.get("gameday"), r.get("gametime")))
    print(f"target: season {season} week {week} — {len(wk)} games")
    return wk, season, week


# ---------------------------------------------------------------- helpers
def norm_name(s):
    """'S.Darnold' / 'Sam Darnold' -> 'darnold' (last name, ascii, lower)."""
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z. ]", "", s).strip()
    parts = re.split(r"[. ]+", s)
    return parts[-1].lower() if parts else ""


def fmt_time(r):
    t = (r.get("gametime") or "").strip()
    if not t:
        return "TBD"
    try:
        hh, mm = t.split(":")
        h = int(hh)
        ap = "AM" if h < 12 else "PM"
        h12 = h % 12 or 12
        return f"{h12}:{mm} {ap} ET"
    except ValueError:
        return t


def spread_txt(r, away, home):
    s = r.get("spread_line")
    try:
        v = float(s)
    except (TypeError, ValueError):
        return None
    # nflverse: positive spread_line = home favored
    if v > 0:
        return f"{home} -{v:g}"
    if v < 0:
        return f"{away} -{-v:g}"
    return "PK"


# ---------------------------------------------------------------- leans
def build_leans(g, edge, wx):
    """wx = matching free-site game dict (forecast) or None (outside window)."""
    leans = []
    away, home = g["away"], g["home"]
    wind = wx.get("wind") if wx and not wx.get("dome") else None
    temp = wx.get("temp") if wx and not wx.get("dome") else None

    # REF total lean — crew tendency alone, no forecast needed
    ref = edge.get("ref")
    if ref and ref.get("n", 0) >= 80:
        if ref["overPct"] >= 57:
            leans.append(dict(k="REF TOTAL", side="OVER", game=f"{away}@{home}",
                who=ref["name"],
                why=f"{ref['overPct']}% overs across {ref['n']} games · {ref['ppg']} pts/gm ({ref['vslg']:+g} vs league)"))
        elif ref["overPct"] <= 43:
            leans.append(dict(k="REF TOTAL", side="UNDER", game=f"{away}@{home}",
                who=ref["name"],
                why=f"only {ref['overPct']}% overs across {ref['n']} games · {ref['ppg']} pts/gm ({ref['vslg']:+g} vs league)"))

    # SPOT leans from badges
    for b in edge.get("badges", []):
        if b["k"] == "WEST AT NIGHT":
            leans.append(dict(k="SPOT", side="UNDER", game=f"{away}@{home}",
                who=b["team"], why=f"{b['txt']} — {b.get('rec','')}"))
        elif b["k"] in ("BODY CLOCK", "CROSS-COUNTRY") and b.get("rec"):
            leans.append(dict(k="SPOT", side="WATCH", game=f"{away}@{home}",
                who=b["team"], why=f"{b['txt']} — {b.get('rec','')}"))

    # weather-dependent leans need a forecast
    if wind is not None and wind >= 15:
        for nm, q in (edge.get("qbs") or {}).items():
            s = q.get("windy")
            if s and s.get("g", 0) >= 5 and s.get("delta", 0) <= -8:
                leans.append(dict(k="QB WIND", side="UNDER", game=f"{away}@{home}",
                    who=f"{nm} ({q['team']})", prop="pass yds",
                    why=f"forecast {wind} mph · {s['ypg']} ypg in wind ({s['delta']}% vs {q['base']['ypg']} norm, {s['g']} gms)"))
        for nm, k in (edge.get("kickers") or {}).items():
            w = k.get("windy")
            if w and w.get("att", 0) >= 8 and w.get("pct", 100) <= 75:
                leans.append(dict(k="KICKER", side="UNDER", game=f"{away}@{home}",
                    who=f"{nm} ({k['team']})", prop="kicking pts",
                    why=f"forecast {wind} mph · {w['pct']}% in wind ({w['made']}/{w['att']}) vs {k['all']['pct']}% career"))

    if temp is not None and temp < 40:
        for t in (away, home):
            w = (edge.get("teamWx") or {}).get(t)
            c = (w or {}).get("cold")
            if c and c.get("n", 0) >= 10 and c.get("delta", 0) <= -8:
                leans.append(dict(k="COLD", side="UNDER", game=f"{away}@{home}",
                    who=t, prop="team total",
                    why=f"forecast {temp}° · {c['ppg']} pts/gm in sub-40 games ({c['delta']}% vs {w['basePpg']} norm, {c['n']} gms)"))
        for nm, q in (edge.get("qbs") or {}).items():
            s = q.get("cold")
            if s and s.get("g", 0) >= 5 and s.get("delta", 0) <= -10:
                leans.append(dict(k="QB COLD", side="UNDER", game=f"{away}@{home}",
                    who=f"{nm} ({q['team']})", prop="pass yds",
                    why=f"forecast {temp}° · {s['ypg']} ypg in cold ({s['delta']}% vs {q['base']['ypg']} norm, {s['g']} gms)"))

    # Denver altitude book — visiting kicker history at altitude
    if home == "DEN":
        for nm, k in (edge.get("kickers") or {}).items():
            alt = k.get("altitude")
            if k.get("team") == away and alt and alt.get("att", 0) >= 6:
                edge_v = alt["pct"] - k["all"]["pct"]
                leans.append(dict(k="ALTITUDE", side="WATCH", game=f"{away}@{home}",
                    who=f"{nm} ({k['team']})", prop="kicking pts",
                    why=f"{alt['pct']}% at altitude ({alt['made']}/{alt['att']}) vs {k['all']['pct']}% career ({edge_v:+d}%) — ball flies ~5% farther in Denver"))
    return leans


# ---------------------------------------------------------------- odds props
def fetch_props(week_rows):
    """Live prop lines keyed by (game, market, last-name). Fully guarded —
    prop market keys drift; failure just means leans post without prices."""
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        print("props: no ODDS_API_KEY — leans post without live prices")
        return {}
    codes = {(g["away"], g["home"]) for g in week_rows}
    out = {}
    try:
        events = WB.get_json(EVENTS_URL.format(key=key), tries=2)
    except Exception as e:
        print(f"props: events endpoint unavailable ({e})")
        return {}
    used = 0
    for ev in events:
        a = WB.ODDS_TEAM_NAMES.get(ev.get("away_team"))
        h = WB.ODDS_TEAM_NAMES.get(ev.get("home_team"))
        if not a or not h or (a, h) not in codes:
            continue
        if used >= 16:   # credit guard — one call per game max
            break
        try:
            data = WB.get_json(EVENT_ODDS_URL.format(
                eid=ev["id"], key=key, mkts=PROP_MARKETS), tries=1)
            used += 1
        except Exception as e:
            print(f"props: {a}@{h} skipped ({e})")
            continue
        for bk in data.get("bookmakers", []):
            for mk in bk.get("markets", []):
                for oc in mk.get("outcomes", []):
                    if oc.get("point") is None:
                        continue
                    kk = (f"{a}@{h}", mk.get("key"), norm_name(oc.get("description") or ""))
                    out.setdefault(kk, []).append(
                        dict(side=oc.get("name"), point=oc["point"], price=oc.get("price")))
    print(f"props: priced {len(out)} (game, market, player) combos from {used} events")
    return out


def attach_prices(leans, props):
    MKT = {"pass yds": "player_pass_yds", "kicking pts": "player_kicking_points"}
    for ln in leans:
        m = MKT.get(ln.get("prop"))
        if not m or not ln.get("who"):
            continue
        nm = norm_name(ln["who"].split("(")[0])
        rows = props.get((ln["game"], m, nm))
        if not rows:
            continue
        side = "Under" if ln["side"] == "UNDER" else "Over"
        pick = [r for r in rows if r["side"] == side] or rows
        pts = [r["point"] for r in pick]
        prices = [r["price"] for r in pick if r.get("price") is not None]
        ln["line"] = statistics.median(pts)
        if prices:
            ln["price"] = int(statistics.median(prices))
        ln["books"] = len(pick)
    return leans


# ---------------------------------------------------------------- main
def main():
    deep = json.load(open(DEEP)) if os.path.exists(DEEP) else {}
    print(f"deep layer: {len(deep.get('refs', {}))} refs · "
          f"{len(deep.get('qbs', {}))} QBs · {len(deep.get('kickers', {}))} kickers")

    free = {}
    if os.path.exists(FREE_DATA):
        try:
            fd = json.load(open(FREE_DATA))
            free = {(g["away"], g["home"]): g for g in fd.get("games", [])}
        except Exception as e:
            print(f"free data.json unreadable ({e}) — no forecasts")
    print(f"forecast games available: {len(free)}")

    rows, season, week = load_week()
    if not rows:
        json.dump(dict(updated=datetime.now(WB.ET).strftime("%Y-%m-%d %H:%M ET"),
                       season=None, week=None, games=[], leans=[],
                       note="No upcoming NFL games on the schedule."),
                  open(OUT, "w"))
        print("no upcoming games — wrote empty board")
        return

    games, all_leans = [], []
    for r in rows:
        away = WB.TEAM_FIX.get(r["away_team"], r["away_team"]) if hasattr(WB, "TEAM_FIX") else r["away_team"]
        home = WB.TEAM_FIX.get(r["home_team"], r["home_team"]) if hasattr(WB, "TEAM_FIX") else r["home_team"]
        edge = WB.build_edge(r, away, home, deep)
        wx = free.get((away, home))
        g = dict(
            away=away, home=home, date=r.get("gameday"), time=fmt_time(r),
            day=datetime.strptime(r["gameday"], "%Y-%m-%d").strftime("%a"),
            stadium=(STADIUMS.get(home) or {}).get("name", r.get("stadium", "")),
            spread=spread_txt(r, away, home),
            total=(float(r["total_line"]) if (r.get("total_line") or "").strip() else None),
            roof=r.get("roof"), edge=edge,
            wx=(dict(temp=wx["temp"], wind=wx["wind"], sky=wx.get("sky"),
                     dome=wx.get("dome", False)) if wx else None))
        leans = build_leans(g, edge, wx)
        g["leans"] = leans
        all_leans.extend(leans)
        games.append(g)

    props = fetch_props(games)
    attach_prices(all_leans, props)

    fc_missing = sum(1 for g in games if g["wx"] is None)
    notes = []
    if fc_missing:
        notes.append(f"Weather leans activate when kickoffs enter the 16-day "
                     f"forecast window ({fc_missing} of {len(games)} games still outside it).")
    if not any(g["edge"].get("ref") for g in games):
        notes.append("Referee assignments post Thu–Fri of game week — crew leans load then.")

    out = dict(
        updated=datetime.now(WB.ET).strftime("%Y-%m-%d %H:%M ET"),
        season=season, week=week, games=games, leans=all_leans,
        note=" ".join(notes))
    json.dump(out, open(OUT, "w"))
    print(f"wrote {OUT}: {len(games)} games · {len(all_leans)} leans")

    # archive for public grading
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    arc = os.path.join(ARCHIVE_DIR, f"{season}-w{week}.json")
    json.dump(dict(built=out["updated"], season=season, week=week,
                   leans=all_leans,
                   games=[dict(away=g["away"], home=g["home"], date=g["date"],
                               spread=g["spread"], total=g["total"]) for g in games]),
              open(arc, "w"))
    print(f"archived predictions -> {arc}")


if __name__ == "__main__":
    main()
