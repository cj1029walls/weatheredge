#!/usr/bin/env python3
"""DFSRADAR PRO — CFB Trench Edge board -> site/pro/cfb.json

The layer the backtest validated (2021-2024, 5,916 FBS offense-games):
OL-vs-opposing-DL weight edge, centered against the league norm, splits
rushing output into a monotone ladder — top-quintile edges rush for
+0.4 yards per carry over bottom-quintile. That, plus our weather layer,
is the board: per-game trench edges quintile-ranked, RUSH EDGE / RUSH FADE
flags, and STACKED flags when a big trench edge meets a windy (run-script)
forecast. No ATS or totals claims — the backtest said no, so we don't.

Data: CollegeFootballData.com (CFBD_API_KEY — already a repo secret).
Weather joined from the free radar's site/cfb/data.json (same game ids).
Backtest receipts embedded from data/cfb/trench_backtest.json.

Leans archived to data/pro/cfb_predictions/ for public grading against
actual rushing box scores once games complete.

No third-party dependencies.
"""
import functools, json, os, statistics, sys, time, urllib.request
from datetime import datetime, timedelta, timezone

print = functools.partial(print, flush=True)

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
OUT = os.path.join(ROOT, "site", "pro", "cfb.json")
FREE = os.path.join(ROOT, "site", "cfb", "data.json")
BACKTEST = os.path.join(ROOT, "data", "cfb", "trench_backtest.json")
ARCH = os.path.join(ROOT, "data", "pro", "cfb_predictions")
TEASER = os.path.join(ROOT, "site", "cfb", "teaser.json")
PASS_FIRST = 0.44   # run rate below this = pass-first; no rushing-prop TARGET

CFBD = "https://api.collegefootballdata.com"
ET = timezone(timedelta(hours=-4))
OL_POS = {"OL", "OT", "OG", "C", "G", "T"}
DL_POS = {"DL", "DT", "DE", "NT", "EDGE"}
WINDY = 15


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


def rush_identity(prior):
    """Last-season team rushing identity: attempts/gm and run rate.
    From CFBD season stats; returns {team: {att, rate}} (empty on any failure)."""
    out = {}
    try:
        rows = fetch(f"{CFBD}/stats/season?year={prior}", tries=2)
        agg = {}
        for r in rows:
            t, name = gv(r, "team"), gv(r, "statName", "stat_name")
            v = gv(r, "statValue", "stat_value")
            if t is None or name is None or v is None:
                continue
            try:
                agg.setdefault(t, {})[name] = float(v)
            except (TypeError, ValueError):
                continue
        for t, st in agg.items():
            ra, pa, g = st.get("rushingAttempts"), st.get("passAttempts"), st.get("games")
            if ra and pa and g:
                out[t] = dict(att=round(ra / g, 1), rate=round(ra / (ra + pa), 3))
    except Exception as e:
        print(f"rush identity unavailable ({e})")
    print(f"rush identity: {len(out)} teams from {prior}")
    return out


def top_rushers(prior, current_rosters):
    """Each team's top returning rusher: last season's leader by yards who is
    still on this season's roster. {team: {name, car, yds, ypc}}."""
    out = {}
    try:
        rows = fetch(f"{CFBD}/stats/player/season?year={prior}&category=rushing", tries=2)
        players = {}
        for r in rows:
            t, nm = gv(r, "team"), gv(r, "player")
            st = (gv(r, "statType", "stat_type") or "").upper()
            v = gv(r, "stat")
            if not t or not nm or v is None:
                continue
            try:
                players.setdefault((t, nm), {})[st] = float(v)
            except (TypeError, ValueError):
                continue
        for (t, nm), st in players.items():
            yds, car = st.get("YDS"), st.get("CAR")
            if not yds or not car or car < 60:
                continue
            cur = current_rosters.get(t)
            if cur is not None and nm not in cur:
                continue                      # transferred / graduated / drafted
            best = out.get(t)
            if not best or yds > best["yds"]:
                out[t] = dict(name=nm, car=int(car), yds=int(yds),
                              ypc=round(yds / car, 1))
    except Exception as e:
        print(f"returning rushers unavailable ({e})")
    print(f"returning rushers: {len(out)} teams")
    return out


def build_trench(year):
    fbs = {gv(t, "school") for t in fetch(f"{CFBD}/teams/fbs?year={year}")}
    roster = fetch(f"{CFBD}/roster?year={year}")
    tw, names = {}, {}
    for p in roster:
        team, w = gv(p, "team"), gv(p, "weight")
        fn, ln = gv(p, "firstName", "first_name"), gv(p, "lastName", "last_name")
        if team and (fn or ln):
            names.setdefault(team, set()).add(f"{fn or ''} {ln or ''}".strip())
        pos = (gv(p, "position") or "").upper()
        if not team or not w or not (180 <= w <= 420):
            continue
        grp = "ol" if pos in OL_POS else "dl" if pos in DL_POS else None
        if grp:
            tw.setdefault(team, {"ol": [], "dl": []})[grp].append(w)
    trench = {t: dict(ol=round(statistics.mean(v["ol"]), 1),
                      dl=round(statistics.mean(v["dl"]), 1))
              for t, v in tw.items()
              if t in fbs and len(v["ol"]) >= 8 and len(v["dl"]) >= 6}
    lg_ol = round(statistics.mean(v["ol"] for v in trench.values()), 1)
    lg_dl = round(statistics.mean(v["dl"] for v in trench.values()), 1)
    print(f"trench data: {len(trench)} FBS teams · league OL {lg_ol} / DL {lg_dl}")
    return trench, lg_ol, lg_dl, names


def main():
    now = datetime.now(ET)
    season = now.year if now.month >= 7 else now.year - 1
    trench, lg_ol, lg_dl, roster_names = build_trench(season)
    lg_diff = lg_ol - lg_dl
    identity = rush_identity(season - 1)
    rbs = top_rushers(season - 1, roster_names)

    games = fetch(f"{CFBD}/games?year={season}&seasonType=regular")
    fbs_games = []
    for g in games:
        hc = (gv(g, "homeClassification", "home_division") or "").lower()
        ac = (gv(g, "awayClassification", "away_division") or "").lower()
        if hc == "fbs" and ac == "fbs":
            fbs_games.append(g)

    # quintile cuts from the FULL season's matchup set (stable, not weekly-noisy)
    all_cd = []
    for g in fbs_games:
        h, a = gv(g, "homeTeam", "home_team"), gv(g, "awayTeam", "away_team")
        th, ta = trench.get(h), trench.get(a)
        if th and ta:
            all_cd.append(round(th["ol"] - ta["dl"] - lg_diff, 1))
            all_cd.append(round(ta["ol"] - th["dl"] - lg_diff, 1))
    all_cd.sort()
    qs = [all_cd[int(len(all_cd) * k / 5)] for k in range(1, 5)] if len(all_cd) >= 50 else [-4, -1, 1, 4]
    print(f"season quintile cuts (lbs/man vs league norm): {qs}")

    def qlabel(cd):
        if cd < qs[0]: return 1
        if cd < qs[1]: return 2
        if cd < qs[2]: return 3
        if cd < qs[3]: return 4
        return 5

    # upcoming window: next 9 days of unplayed games; else next scheduled week
    def gdate(g):
        s = gv(g, "startDate", "start_date") or ""
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    future = [g for g in fbs_games
              if gv(g, "homePoints", "home_points") is None
              and (d := gdate(g)) and d > now.astimezone(timezone.utc) - timedelta(hours=6)]
    near = [g for g in future
            if gdate(g) <= now.astimezone(timezone.utc) + timedelta(days=9)]
    pool = near or future
    if not pool:
        json.dump(dict(updated=now.strftime("%Y-%m-%d %H:%M ET"), season=season,
                       week=None, games=[], leans=[],
                       note="No upcoming FBS games on the schedule."),
                  open(OUT, "w"))
        print("no upcoming games — wrote empty board")
        return
    week = min(gv(g, "week") for g in pool)
    wk_games = sorted([g for g in future if gv(g, "week") == week],
                      key=lambda g: gv(g, "startDate", "start_date") or "")
    print(f"target: {season} week {week} — {len(wk_games)} FBS games")

    # lines for the week (median across books)
    lines = {}
    try:
        for L in fetch(f"{CFBD}/lines?year={season}&seasonType=regular&week={week}", tries=2):
            gid = gv(L, "id", "gameId")
            sp = [gv(x, "spread") for x in (L.get("lines") or []) if gv(x, "spread") is not None]
            tt = [gv(x, "overUnder", "over_under") for x in (L.get("lines") or [])
                  if gv(x, "overUnder", "over_under") is not None]
            if gid:
                lines[gid] = dict(spread=(statistics.median(sp) if sp else None),
                                  total=(statistics.median(tt) if tt else None))
    except Exception as e:
        print(f"lines unavailable ({e})")

    # weather from the free radar (joined on CFBD game id)
    wx = {}
    if os.path.exists(FREE):
        try:
            for g in json.load(open(FREE)).get("games", []):
                wx[str(g.get("id"))] = g
        except Exception:
            pass
    print(f"forecast games available: {len(wx)}")

    out_games, leans = [], []
    for g in wk_games:
        h, a = gv(g, "homeTeam", "home_team"), gv(g, "awayTeam", "away_team")
        th, ta = trench.get(h), trench.get(a)
        gid = gv(g, "id")
        d = gdate(g)
        et_dt = d.astimezone(ET) if d else None
        ln = lines.get(gid) or {}
        w = wx.get(str(gid))
        def edge(off, deff, off_t, def_t):
            if not off_t or not def_t:
                return None
            cd = round(off_t["ol"] - def_t["dl"] - lg_diff, 1)
            return dict(team=off, cdiff=cd, q=qlabel(cd),
                        ol=off_t["ol"], oppDl=def_t["dl"])
        ae, he = edge(a, h, ta, th), edge(h, a, th, ta)
        entry = dict(
            id=gid, away=a, home=h, week=week,
            day=(et_dt.strftime("%a %b %-d") if et_dt else "TBD"),
            time=(et_dt.strftime("%-I:%M %p ET") if et_dt else "TBD"),
            spread=ln.get("spread"), total=ln.get("total"),
            awayEdge=ae, homeEdge=he,
            wx=(dict(temp=w.get("temp"), wind=w.get("wind"),
                     dome=bool(w.get("dome")), sky=w.get("sky")) if w else None))
        out_games.append(entry)
        for e in (ae, he):
            if not e:
                continue
            opp = h if e["team"] == a else a
            windy_kick = bool(w and not w.get("dome") and (w.get("wind") or 0) >= WINDY)
            ident = identity.get(e["team"])
            rb = rbs.get(e["team"])
            if e["q"] == 5 and ident and ident["rate"] < PASS_FIRST:
                # stacked line on a pass-first offense: real edge, wrong market.
                # Stays on the board with its quintile; no rushing-prop TARGET.
                print(f"  demoted (pass-first {ident['rate']:.0%}): {e['team']}")
                continue
            if e["q"] == 5:
                why = (f"+{e['cdiff']} lbs/man trench edge vs league norm "
                       f"(their OL {e['ol']} vs {opp} DL {e['oppDl']}) — "
                       f"top-quintile edges rushed for +0.4 YPC in our 4-season backtest")
                if windy_kick:
                    leans.append(dict(k="STACKED RUSH", side="TARGET", who=e["team"],
                        rush=ident, rb=rb,
                        game=f"{a} @ {h}", cd=e["cdiff"],
                        why=why + f" · {w['wind']} mph forecast leans the script run-heavy"))
                else:
                    leans.append(dict(k="RUSH EDGE", side="TARGET", who=e["team"],
                        rush=ident, rb=rb,
                                      game=f"{a} @ {h}", cd=e["cdiff"], why=why))
            elif e["q"] == 1:
                leans.append(dict(k="RUSH FADE", side="FADE", who=e["team"],
                        rush=ident, rb=rb,
                    game=f"{a} @ {h}", cd=e["cdiff"],
                    why=(f"{e['cdiff']} lbs/man vs league norm (their OL {e['ol']} vs "
                         f"{opp} DL {e['oppDl']}) — bottom-quintile edges averaged "
                         f"0.4 fewer YPC in the backtest")))
    # keep the board scannable: biggest edges first, targets and fades each capped
    # so one side never crowds the other off the board
    order = {"STACKED RUSH": 0, "RUSH EDGE": 1}
    targets = sorted([l for l in leans if l["side"] == "TARGET"],
                     key=lambda l: (order.get(l["k"], 9), -l["cd"]))[:9]
    fades = sorted([l for l in leans if l["side"] == "FADE"],
                   key=lambda l: l["cd"])[:5]
    leans = targets + fades

    backtest = None
    if os.path.exists(BACKTEST):
        try:
            bt = json.load(open(BACKTEST))
            backtest = dict(seasons=bt.get("seasons"), n=bt.get("offenseGames"),
                            ladder=bt.get("centeredBuckets"))
        except Exception:
            pass

    fc_missing = sum(1 for g2 in out_games if g2["wx"] is None)
    notes = []
    if fc_missing:
        notes.append(f"Forecasts join as kickoffs enter the free radar's window "
                     f"({fc_missing} of {len(out_games)} games still outside it).")
    out = dict(updated=now.strftime("%Y-%m-%d %H:%M ET"), season=season, week=week,
               lg=dict(ol=lg_ol, dl=lg_dl), cuts=qs,
               games=out_games, leans=leans, backtest=backtest,
               note=" ".join(notes))
    json.dump(out, open(OUT, "w"), separators=(",", ":"))
    print(f"wrote {OUT}: {len(out_games)} games · {len(leans)} leans")

    # public teaser for the free CFB page (counts only — the board stays gated)
    try:
        json.dump(dict(updated=out["updated"], week=week,
                       targets=sum(1 for l in leans if l["side"] == "TARGET"),
                       fades=sum(1 for l in leans if l["side"] == "FADE"),
                       stacked=sum(1 for l in leans if l["k"] == "STACKED RUSH")),
                  open(TEASER, "w"), separators=(",", ":"))
        print("wrote free-page teaser")
    except Exception as e:
        print(f"teaser skipped ({e})")

    os.makedirs(ARCH, exist_ok=True)
    json.dump(dict(built=out["updated"], season=season, week=week, leans=leans,
                   games=[dict(id=g2["id"], away=g2["away"], home=g2["home"],
                               awayEdge=g2["awayEdge"], homeEdge=g2["homeEdge"])
                          for g2 in out_games]),
              open(os.path.join(ARCH, f"{season}-w{week}.json"), "w"),
              separators=(",", ":"))
    print("archived predictions")


if __name__ == "__main__":
    main()
