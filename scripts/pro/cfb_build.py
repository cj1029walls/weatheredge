#!/usr/bin/env python3
"""DFSRADAR PRO — CFB Trench Edge board -> site/pro/cfb.json

The layer the backtest validated (2021-2024, 5,916 FBS offense-games):
OL-vs-opposing-DL weight edge, centered against the league norm, splits
rushing output into a monotone ladder — top-quintile edges rush for
+0.4 yards per carry over bottom-quintile. That, plus our weather layer,
is the board: per-game trench edges quintile-ranked, RUSH EDGE / RUSH FADE
flags, and STACKED flags when a big trench edge meets a windy (run-script)
forecast. No ATS or totals claims — the backtest said no, so we don't.

Data: CollegeFootballData.com (CFBD_API_KEY — already a repo secret), read
through scripts/cfb/cfbd_cache.py. Almost everything the board needs is
season-static (FBS list, rosters, last season's stats, the season schedule), so
when CFBD is down the board is still built for the right week from cache and its
note says which data is not fresh; with no cache at all, the last board is kept
and labelled "not refreshed" instead of silently showing last week.
Weather joined from the free radar's site/cfb/data.json (same game ids).
Backtest receipts embedded from data/cfb/trench_backtest.json.

Leans archived to data/pro/cfb_predictions/ for public grading against
actual rushing box scores once games complete.

No third-party dependencies.
"""
import functools, json, os, statistics, sys, urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

print = functools.partial(print, flush=True)

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.join(ROOT, "scripts", "cfb"))
import cfbd_cache as cfbd       # noqa: E402 — every CFBD call goes through the cache
OUT = os.path.join(ROOT, "site", "pro", "cfb.json")
FREE = os.path.join(ROOT, "site", "cfb", "data.json")
BACKTEST = os.path.join(ROOT, "data", "cfb", "trench_backtest.json")
ARCH = os.path.join(ROOT, "data", "pro", "cfb_predictions")
TEASER = os.path.join(ROOT, "site", "cfb", "teaser.json")
PASS_FIRST = 0.44   # run rate below this = pass-first; no rushing-prop TARGET

ODDS_EVENTS = ("https://api.the-odds-api.com/v4/sports/americanfootball_ncaaf/"
               "events?apiKey={key}")
ODDS_EVENT = ("https://api.the-odds-api.com/v4/sports/americanfootball_ncaaf/"
              "events/{eid}/odds?apiKey={key}&regions=us&markets=player_rush_yds"
              "&oddsFormat=american")
ET = ZoneInfo("America/New_York")   # a fixed -4 mislabels kickoffs after DST ends
OL_POS = {"OL", "OT", "OG", "C", "G", "T"}
DL_POS = {"DL", "DT", "DE", "NT", "EDGE"}
RB_POS = {"RB", "FB", "HB", "TB"}       # a rush-prop lean must name an actual back
WINDY = 15
BRAND = {}


def gv(d, *names):
    for n in names:
        if n in d and d[n] is not None:
            return d[n]
    return None


def rush_identity(prior):
    """Last-season team rushing identity: attempts/gm and run rate.
    From CFBD season stats; returns {team: {att, rate}} (empty on any failure)."""
    out = {}
    try:
        rows = cfbd.get("/stats/season", year=prior)
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


def top_rushers(prior, current_rosters, current_backs):
    """Each team's top returning RUNNING BACK: last season's leader by rushing
    yards who is still on this season's roster AND is listed at RB/FB.
    {team: {name, car, yds, ypc}}.

    The position filter is not optional. Without it the leader on a run-heavy
    roster is often the quarterback, and the card then names a QB as the back
    to play — with a live rushing-yards line attached to him."""
    out, skipped_qb = {}, 0
    try:
        rows = cfbd.get("/stats/player/season", year=prior, category="rushing")
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
            if nm not in (current_backs.get(t) or set()):
                skipped_qb += 1               # QB/WR rushing leader, or no position data
                continue
            best = out.get(t)
            if not best or yds > best["yds"]:
                out[t] = dict(name=nm, car=int(car), yds=int(yds),
                              ypc=round(yds / car, 1))
    except Exception as e:
        print(f"returning rushers unavailable ({e})")
    print(f"returning rushers: {len(out)} teams "
          f"({skipped_qb} non-RB rushing leaders excluded)")
    return out


def build_trench(year):
    teams_raw = cfbd.get("/teams/fbs", year=year)
    fbs = {gv(t, "school") for t in teams_raw}
    global BRAND
    BRAND = {gv(t, "school"): dict(color=gv(t, "color"),
                                   ab=gv(t, "abbreviation") or (gv(t, "school") or "")[:4].upper())
             for t in teams_raw}
    roster = cfbd.get("/roster", year=year)
    tw, names, backs = {}, {}, {}
    for p in roster:
        team, w = gv(p, "team"), gv(p, "weight")
        fn, ln = gv(p, "firstName", "first_name"), gv(p, "lastName", "last_name")
        pos = (gv(p, "position") or "").upper()
        if team and (fn or ln):
            full = f"{fn or ''} {ln or ''}".strip()
            names.setdefault(team, set()).add(full)
            if pos in RB_POS:
                backs.setdefault(team, set()).add(full)
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
    print(f"roster backs: {sum(len(v) for v in backs.values())} RB/FB across {len(backs)} teams")
    return trench, lg_ol, lg_dl, names, backs


def attach_rush_props(leans):
    key = os.environ.get("ODDS_API_KEY")
    named = [l for l in leans if l.get("rb")]
    if not key or not named:
        print("rush props: skipped (no key or no named backs)")
        return
    import unicodedata as _ud, re as _re
    def last(nm):
        # "Telly Johnson Jr." used to reduce to "" (trailing dot), and "" then
        # matched every other "Jr." in the event — a stranger's line on our back
        nm = _ud.normalize("NFKD", nm or "").encode("ascii", "ignore").decode()
        parts = [p for p in _re.split(r"[. ]+", _re.sub(r"[^A-Za-z. ]", "", nm).strip())
                 if p and p.lower() not in ("jr", "sr", "ii", "iii", "iv")]
        return parts[-1].lower() if parts else ""
    def odds_get(url):
        req = urllib.request.Request(url, headers={"User-Agent": "dfsradar-build/1.0"})
        with urllib.request.urlopen(req, timeout=45) as r:
            return json.loads(r.read())
    try:
        events = odds_get(ODDS_EVENTS.format(key=key))      # free: no credits
    except Exception as e:
        print(f"rush props: events unavailable ({e})")
        return
    # Credits are spent per event call. Never price a game already under way
    # (in-play lines are not what the lean was made against) and don't buy
    # prop markets days before books post them.
    utc_now = datetime.now(timezone.utc)
    def pregame(ev):
        try:
            t = datetime.fromisoformat(ev["commence_time"].replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError):
            return False
        return utc_now + timedelta(minutes=5) < t <= utc_now + timedelta(hours=72)
    events = [ev for ev in events if pregame(ev)]
    # match Odds API team names ("Oklahoma Sooners") to CFBD schools ("Oklahoma")
    def match_event(game):
        away, home = [x.strip() for x in game.split("@")]
        for ev in events:
            ea, eh = ev.get("away_team") or "", ev.get("home_team") or ""
            if eh.startswith(home) and ea.startswith(away):
                return ev
        return None
    used, priced = 0, 0
    for l in named:
        if used >= 10:
            break
        ev = match_event(l["game"])
        if not ev:
            continue
        try:
            data = odds_get(ODDS_EVENT.format(eid=ev["id"], key=key))
            used += 1
        except Exception as e:
            print(f"rush props: {l['game']} skipped ({e})")
            continue
        want = last(l["rb"]["name"])
        pts, prices, who = [], [], set()
        side = "Over" if l["side"] == "TARGET" else "Under"
        for bk in data.get("bookmakers", []):
            for mk in bk.get("markets", []):
                if mk.get("key") != "player_rush_yds":
                    continue
                for oc in mk.get("outcomes", []):
                    if oc.get("point") is None or last(oc.get("description") or "") != want:
                        continue
                    if oc.get("name") != side:
                        continue
                    pts.append(oc["point"])
                    who.add(oc.get("description"))
                    if oc.get("price") is not None:
                        prices.append(oc["price"])
        if len(who) > 1 or not want:
            print(f"rush props: {l['game']} — '{want}' matches {sorted(map(str, who))}; left unpriced")
            continue
        if pts:
            l["line"] = statistics.median(pts)
            if prices:
                l["price"] = int(statistics.median(prices))
            l["books"] = len(pts)
            priced += 1
    if events and named and not used:
        print(f"::warning::rush props: none of {len(named)} named backs' games matched an Odds "
              "API event — check CFBD vs Odds API school names")
    print(f"rush props: priced {priced}/{len(named)} named backs from {used} event calls")


def main():
    now = datetime.now(ET)
    season = now.year if now.month >= 7 else now.year - 1
    trench, lg_ol, lg_dl, roster_names, roster_backs = build_trench(season)
    lg_diff = lg_ol - lg_dl
    identity = rush_identity(season - 1)
    rbs = top_rushers(season - 1, roster_names, roster_backs)

    games = cfbd.get("/games", year=season, seasonType="regular")
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
                       note=("Regular season complete — the Trench Edge board covers regular-season "
                             "weeks only. Bowl and playoff weather is on the free CFB radar; the "
                             "board returns for Week 1." if now.month in (12, 1) else
                             "No upcoming FBS games on the schedule.")),
                  open(OUT, "w"))
        print("no upcoming games — wrote empty board")
        return
    week = min(gv(g, "week") for g in pool)
    wk_games = sorted([g for g in future if gv(g, "week") == week],
                      key=lambda g: gv(g, "startDate", "start_date") or "")
    print(f"target: {season} week {week} — {len(wk_games)} FBS games")

    # lines for the week (median across books) — filtered from the season-wide
    # response the free slate build already cached this run (no extra call)
    lines = {}
    try:
        for L in cfbd.get("/lines", year=season, seasonType="regular"):
            if gv(L, "week") not in (None, week):
                continue
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
            # ISO kickoff so the desk can tell a finished board from this week's
            kick=(d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if d else None),
            spread=ln.get("spread"), total=ln.get("total"),
            awayEdge=ae, homeEdge=he,
            awayColor=(BRAND.get(a) or {}).get("color"),
            homeColor=(BRAND.get(h) or {}).get("color"),
            awayAb=(BRAND.get(a) or {}).get("ab"), homeAb=(BRAND.get(h) or {}).get("ab"),
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

    # v6: join live rushing-prop lines onto leans that name a back. Coverage
    # is book- and game-dependent (bigger games only) — a missing line is
    # normal and shown honestly; guarded so odds failures never break a build.
    attach_rush_props(leans)

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
    st = cfbd.status()
    if st:
        notes.append(f"⚠ {cfbd.stale_note('schedule, rosters & lines')} "
                     f"Board rebuilt from that cached data {now.strftime('%a %-I:%M %p ET')}.")
    if fc_missing:
        notes.append(f"Forecasts join as kickoffs enter the free radar's window "
                     f"({fc_missing} of {len(out_games)} games still outside it).")
    out = dict(updated=now.strftime("%Y-%m-%d %H:%M ET"), season=season, week=week,
               lg=dict(ol=lg_ol, dl=lg_dl), cuts=qs,
               games=out_games, leans=leans, backtest=backtest,
               note=" ".join(notes))
    if st:
        out.update(stale=True, status=st)
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

    # A lean is final once its game kicks off (or leaves the board after it is
    # played): keep the version archived before kickoff. Rewriting the whole
    # file meant Saturday's post-kickoff refresh replaced graded leans, and
    # Thursday/Friday leans vanished once those games finished.
    os.makedirs(ARCH, exist_ok=True)
    arch_path = os.path.join(ARCH, f"{season}-w{week}.json")
    utc_now = now.astimezone(timezone.utc)
    open_games = {f"{g2['away']} @ {g2['home']}" for g2, g in zip(out_games, wk_games)
                  if (d := gdate(g)) and d > utc_now}
    arch_leans, arch_games = leans, [dict(id=g2["id"], away=g2["away"], home=g2["home"],
                                          awayEdge=g2["awayEdge"], homeEdge=g2["homeEdge"])
                                     for g2 in out_games]
    try:
        prev = json.load(open(arch_path)) if os.path.exists(arch_path) else None
    except Exception:
        prev = None
    if prev and prev.get("week") == week:
        frozen = [l for l in prev.get("leans") or [] if l.get("game") not in open_games]
        arch_leans = frozen + [l for l in leans if l.get("game") in open_games]
        seen = {g2["id"] for g2 in arch_games}
        arch_games += [g2 for g2 in prev.get("games") or [] if g2.get("id") not in seen]
        print(f"archive: {len(frozen)} lean(s) frozen at kickoff, "
              f"{len(arch_leans) - len(frozen)} still open")
    json.dump(dict(built=out["updated"], season=season, week=week, leans=arch_leans,
                   games=arch_games),
              open(arch_path, "w"), separators=(",", ":"))
    print("archived predictions")


def _board_over(board, grace_hours=5):
    """True when every game on a kept board has been played. Uses the ISO
    `kick` when present, else the 'Sat Sep 19' day label + season year."""
    games = board.get("games") or []
    if not games:
        return False
    now = datetime.now(timezone.utc)
    for g in games:
        k = g.get("kick")
        try:
            if k:
                t = datetime.fromisoformat(k.replace("Z", "+00:00"))
            else:
                t = datetime.strptime(f"{g.get('day')} {board.get('season')}", "%a %b %d %Y")
                t = t.replace(hour=23, minute=59, tzinfo=ET)
        except (TypeError, ValueError):
            return False
        if t + timedelta(hours=grace_hours) > now:
            return False
    return True


def pause_finished_board(why):
    """Outage + a board whose games are all final: clear its leans rather than
    let last week's calls read as this week's. Graded weeks stay on Record."""
    try:
        board = json.load(open(OUT))
    except Exception:
        return
    if not _board_over(board):
        return
    last = (board.get("status") or {}).get("lastGood") or board.get("updated")
    wk = board.get("week")
    board.update(games=[], leans=[], stale=True, paused=True,
                 note=(f"Board paused — our college data source stopped answering after the "
                       f"{last} build. Week {wk} is final and grades on the Record tab; the next "
                       f"Trench Edge board posts as soon as the source is back."))
    json.dump(board, open(OUT, "w"), separators=(",", ":"))
    try:
        json.dump(dict(updated=board.get("updated"), week=None, targets=0, fades=0,
                       stacked=0, stale=True, paused=True), open(TEASER, "w"),
                  separators=(",", ":"))
    except Exception:
        pass
    print(f"::warning title=CFB PRO board paused::Week {wk} board is final and the source is down — leans cleared")


def run():
    try:
        main()
    except cfbd.Unavailable as e:
        # Nothing cached to build from: keep the last board, but make it say
        # so on the page (the desk renders `note`) instead of passing it off
        # as this week's — and clear it entirely once its games are final.
        cfbd.mark_stale(OUT, f"{e.why}. This is the last board that could be built", field="note")
        cfbd.mark_stale(TEASER, e.why, field="note")
        pause_finished_board(e.why)
        print(f"::warning title=CFB PRO board not refreshed::{e}")
    finally:
        cfbd.report("cfb pro board")


if __name__ == "__main__":
    run()
