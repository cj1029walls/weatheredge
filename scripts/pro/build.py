#!/usr/bin/env python3
"""DFSRADAR PRO — nightly HR-prop targets build.

Runs inside the daily workflow AFTER scripts/daily_build.py, so site/data.json
(today's slate with weather edges, plate umps, probable pitchers) is on disk.
Combines four signals into a per-batter HR probability, matches each batter to
live sportsbook prices (site/pro/props.json, published by the odds workflow),
and flags value. All rates are shrunk toward league averages and capped —
no small-sample blowups, ever (see DFSRADAR_PRO_MATH_SPEC.md).

  hr_prob = 1 - (1 - adj_rate)^PA
  adj_rate = shrunk_batter_HR_per_AB x weather x ump x opposing_SP

v3 additions (game-level layer):
  * per-game EXPECTED HRS = sum of per-batter probabilities (a real
    expected-value total, not park-avg x multipliers)
  * runs projections per team -> projected game total vs the market line
  * with-ump split tables (batter / pitcher / BvP with tonight's plate ump)
    joined from statsapi game logs x the ump game caches — DISPLAY ONLY,
    never a multiplier
  * auto-generated intel feed cards

Outputs:
  site/pro/data.json            (deployed with the site, not committed)
  data/pro/predictions/<d>.json (committed — future accuracy grading)

No third-party dependencies.
"""
import functools, json, os, statistics, sys, unicodedata
from datetime import datetime, timedelta, timezone
from archive import save_locked

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from parks import MLBID_TO_CODE

print = functools.partial(print, flush=True)

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
SLATE = os.path.join(ROOT, "site", "data.json")
HITTERS = os.path.join(ROOT, "data", "hitters_history.json")
UMPS = os.path.join(ROOT, "data", "umps_history.json")
UMPS_PRO = os.path.join(ROOT, "site", "pro", "umps.json")
RETRO_CACHE = os.path.join(ROOT, "data", "pro", "ump_games_retro.json")
S2026_CACHE = os.path.join(ROOT, "data", "pro", "ump_games_2026.json")
PROPS = os.path.join(ROOT, "site", "pro", "props.json")
OUT = os.path.join(ROOT, "site", "pro", "data.json")
PRED_DIR = os.path.join(ROOT, "data", "pro", "predictions")

ET = timezone(timedelta(hours=-4))

import time, urllib.request
SCHED_LINEUPS = ("https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={d}"
                 "&hydrate=lineups")
BVP = ("https://statsapi.mlb.com/api/v1/people/{bid}/stats"
       "?stats=vsPlayer&group=hitting&opposingPlayerId={pid}")
GAMELOG = ("https://statsapi.mlb.com/api/v1/people/{pid}/stats"
           "?stats=gameLog&group={grp}&season={season}")
TEAM_STATS = ("https://statsapi.mlb.com/api/v1/teams/stats?sportId=1"
              "&stats=season&group=hitting&season={y}")
SP_SEASON = ("https://statsapi.mlb.com/api/v1/people/{pid}/stats"
             "?stats=season&group=pitching&season={y}")

SPLIT_SEASONS = [2022, 2023, 2024, 2025, 2026]

def get_json(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "dfsradar-pro/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(4 * (i + 1))

def fetch_lineups():
    """(team -> {pid: order 1-9}, team -> {pid: name}) for posted lineups."""
    out, names = {}, {}
    try:
        d = datetime.now(ET).strftime("%m/%d/%Y")
        sched = get_json(SCHED_LINEUPS.format(d=d))
        for day in sched.get("dates", []):
            for g in day.get("games", []):
                lu = g.get("lineups") or {}
                for side, key in (("home", "homePlayers"), ("away", "awayPlayers")):
                    players = lu.get(key) or []
                    if len(players) < 8:
                        continue
                    # map by team id — the schedule payload no longer carries
                    # abbreviations reliably (they came back null Aug 2026)
                    code = MLBID_TO_CODE.get(g["teams"][side]["team"].get("id"))
                    slots = {str(p.get("id")): i + 1 for i, p in enumerate(players)}
                    nm = {str(p.get("id")): (p.get("fullName") or p.get("lastName") or "")
                          for p in players}
                    if code:
                        out[code] = slots
                        names[code] = nm
    except Exception as e:
        print(f"lineups unavailable ({e}) — using flat 4.0 PA")
    return out, names

# team abbreviation quirks between statsapi and our park codes
ABBR_FIX = {"AZ": "ARI", "WSN": "WSH", "SDP": "SD", "SFG": "SF", "TBR": "TB",
            "KCR": "KC", "CHW": "CWS", "ATH": "OAK", "A": "OAK"}

K_BVP = 60
def bvp_mult(bid, pid):
    """Batter-vs-pitcher career HR/AB, shrunk k=60, capped; None if under 10 AB."""
    if not bid or not pid:
        return None, None
    try:
        d = get_json(BVP.format(bid=bid, pid=pid))
        for st in d.get("stats", []):
            for sp in st.get("splits", []):
                stat = sp.get("stat") or {}
                ab, hr = stat.get("atBats"), stat.get("homeRuns")
                if ab is None:
                    continue
                if ab < 10:
                    return None, f"{hr or 0}/{ab}"
                adj = ((hr or 0) + K_BVP * LG_HR_AB) / (ab + K_BVP)
                return clamp(adj / LG_HR_AB, 0.60, 1.75), f"{hr or 0}/{ab}"
    except Exception:
        pass
    return None, None

# league constants + shrinkage (see spec)
LG_HR_AB = 0.032      # league HR per AB

def league_drift():
    """Trailing-14-day league HR environment vs the 2.40/game anchor, from our
    own graded results (runs after grade.py in the workflow, so it is fresh).
    Clamped tight: this tracks slow seasonal drift, not one hot week. Added in
    v4 after game-projection bias flipped +0.24 -> -0.22 across two windows."""
    try:
        res = json.load(open(os.path.join(ROOT, "data", "pro", "results.json")))
        acts = [g["act"] for d in sorted(res["days"])[-14:]
                for g in res["days"][d].get("games", [])]
        if len(acts) >= 40:
            return clamp(statistics.mean(acts) / 2.40, 0.92, 1.08)
    except Exception:
        pass
    return 1.0
K_BAT = 200
LG_UMP_HR = 2.40      # league HR per game
K_UMP = 200
LG_HR9 = 1.05         # league HR per 9 IP
K_SP_IP = 200
PA_PER_GAME = 4.0
LG_ERA = 4.30
LG_RPG_TEAM = 4.45    # league runs per team-game

def clamp(v, lo, hi):
    return max(lo, min(hi, v))

def calibrate(p):
    """Calibration, tuned from graded receipts. Week 1: top bucket overshot,
    slope above 24 cut to 0.55. Week 2 (12 nights, 226 picks): 20-25 bucket
    is dead-on (stated 22.5 -> hit 22.3, n=148) but 25+ still overshoots
    (stated 27.4 -> hit 18.3, n=60) -> slope 0.55 -> 0.40, hard cap 34 -> 30.
    Half-corrections on purpose: n=60 has a wide confidence interval."""
    if p > 23:
        p = 23 + (p - 23) * 0.30
    return min(round(p, 1), 27.0)
    # v4 (20 nights, 374 picks): everything stated 24+ hit ~18% (n=101) while
    # 20-24 stayed calibrated -> knee 24 -> 23, slope 0.40 -> 0.30, cap 30 -> 27

def norm_name(s):
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower().replace(".", "").replace("jr", "").strip()

def batter_rate(games):
    ab = sum(g[2] for g in games)
    hr = sum(g[4] for g in games)
    if ab < 50:
        return None, ab, hr
    adj = (hr + K_BAT * LG_HR_AB) / (ab + K_BAT)
    return adj, ab, hr

def ump_mult(ump, umps_all, umps_pro=None):
    """Prefer the 10-season+current PRO ump dataset (2017-2026, incl. this
    season's games) over the free-side 2019-2025 aggregate. Same shrinkage
    and cap — more games just means the estimate earns more of its signal."""
    name = (ump or {}).get("name")
    if not name:
        return 1.0, None
    if umps_pro and name in umps_pro.get("umps", {}):
        u = umps_pro["umps"][name]
        lg = umps_pro["league"]["hrpg"]
        shrunk = (u["hrpg"] * u["n"] + lg * K_UMP) / (u["n"] + K_UMP)
        return clamp(shrunk / lg, 0.90, 1.10), u["n"]
    if name not in umps_all:
        return 1.0, None
    u = umps_all[name]
    shrunk = (u["hr"] * u["n"] + LG_UMP_HR * K_UMP) / (u["n"] + K_UMP)
    return clamp(shrunk / LG_UMP_HR, 0.90, 1.10), u["n"]

def sp_mult(p):
    """Opposing starting pitcher HR/9, shrunk by innings."""
    if not p or not p.get("all"):
        return 1.0, None
    a = p["all"]
    ip, hr9 = a.get("ip", 0), a.get("hr9")
    if not ip or hr9 is None:
        return 1.0, None
    shrunk = (hr9 * ip + LG_HR9 * K_SP_IP) / (ip + K_SP_IP)
    return clamp(shrunk / LG_HR9, 0.60, 1.60), a.get("n")

# ---------------------------------------------------------------- ump joins

def load_ump_maps():
    """(date_home -> ump, gamePk -> ump). Empty dicts if caches missing."""
    by_dh, by_pk = {}, {}
    try:
        for d, home, _away, ump, _hr, _r in json.load(open(RETRO_CACHE))["games"]:
            by_dh[f"{d}|{home}"] = ump
    except Exception:
        pass
    try:
        for dstr, games in json.load(open(S2026_CACHE)).items():
            d = dstr.replace("-", "")
            for home, _away, ump, _hr, _r, pk in games:
                by_dh[f"{d}|{home}"] = ump
                if pk:
                    by_pk[pk] = ump
    except Exception:
        pass
    return by_dh, by_pk

def ip_to_float(s):
    try:
        w, _, frac = str(s).partition(".")
        return int(w) + int(frac or 0) / 3.0
    except (ValueError, TypeError):
        return 0.0

def game_log(pid, grp):
    """All gameLog splits across SPLIT_SEASONS: list of normalized rows."""
    rows = []
    for season in SPLIT_SEASONS:
        try:
            d = get_json(GAMELOG.format(pid=pid, grp=grp, season=season), tries=2)
        except Exception:
            continue
        for st in d.get("stats", []):
            for sp in st.get("splits", []):
                stat = sp.get("stat") or {}
                team_id = (sp.get("team") or {}).get("id")
                opp_id = (sp.get("opponent") or {}).get("id")
                home_id = team_id if sp.get("isHome") else opp_id
                rows.append(dict(
                    d=(sp.get("date") or "").replace("-", ""),
                    home=MLBID_TO_CODE.get(home_id),
                    pk=(sp.get("game") or {}).get("gamePk"),
                    stat=stat))
        time.sleep(0.06)
    return rows

def match_ump(rows, ump, by_dh, by_pk):
    out = []
    for r in rows:
        u = by_pk.get(r["pk"]) or (by_dh.get(f"{r['d']}|{r['home']}") if r["home"] else None)
        if u == ump:
            out.append(r)
    return out

def agg_bat(rows):
    ab = sum(r["stat"].get("atBats") or 0 for r in rows)
    hr = sum(r["stat"].get("homeRuns") or 0 for r in rows)
    h = sum(r["stat"].get("hits") or 0 for r in rows)
    rbi = sum(r["stat"].get("rbi") or 0 for r in rows)
    bb = sum(r["stat"].get("baseOnBalls") or 0 for r in rows)
    k = sum(r["stat"].get("strikeOuts") or 0 for r in rows)
    return dict(g=len(rows), ab=ab, hr=hr, h=h, rbi=rbi, bb=bb, k=k,
                avg=(f"{h/ab:.3f}".lstrip("0") if ab else "—"))

def agg_pit(rows):
    ip = sum(ip_to_float(r["stat"].get("inningsPitched")) for r in rows)
    er = sum(r["stat"].get("earnedRuns") or 0 for r in rows)
    k = sum(r["stat"].get("strikeOuts") or 0 for r in rows)
    bb = sum(r["stat"].get("baseOnBalls") or 0 for r in rows)
    h = sum(r["stat"].get("hits") or 0 for r in rows)
    return dict(g=len(rows), ip=round(ip, 1),
                era=round(9 * er / ip, 2) if ip else None,
                k=k, bb=bb, h=h,
                k9=round(9 * k / ip, 1) if ip else None,
                bb9=round(9 * bb / ip, 1) if ip else None)

# ---------------------------------------------------------------- main

def main():
    for path, label in ((SLATE, "site/data.json"), (HITTERS, "hitters"), (UMPS, "umps")):
        if not os.path.exists(path):
            sys.exit(f"{label} missing — PRO build must run after the daily build.")
    slate = json.load(open(SLATE))
    hitters = json.load(open(HITTERS))
    umps_all = json.load(open(UMPS))
    umps_pro = json.load(open(UMPS_PRO)) if os.path.exists(UMPS_PRO) else None
    props = json.load(open(PROPS)) if os.path.exists(PROPS) else {"games": []}
    by_dh, by_pk = load_ump_maps()
    print(f"ump maps: {len(by_dh)} date-home keys, {len(by_pk)} gamePks")

    # index props by normalized player name
    odds_by_player = {}
    for pg in props.get("games", []):
        for o in pg.get("hr", []):
            odds_by_player.setdefault(norm_name(o["player"]), o)

    lineups, lu_names = fetch_lineups()
    lineups = {ABBR_FIX.get(k, k): v for k, v in lineups.items()}
    lu_names = {ABBR_FIX.get(k, k): v for k, v in lu_names.items()}
    if lineups:
        print(f"lineups posted for {len(lineups)} teams")

    # team season offense (one call)
    team_off = {}
    try:
        y = datetime.now(ET).year
        d = get_json(TEAM_STATS.format(y=y))
        for st in d.get("stats", []):
            for sp in st.get("splits", []):
                code = MLBID_TO_CODE.get((sp.get("team") or {}).get("id"))
                stat = sp.get("stat") or {}
                gp = stat.get("gamesPlayed") or 0
                if code and gp:
                    team_off[code] = dict(rg=round((stat.get("runs") or 0) / gp, 2),
                                          ops=stat.get("ops"))
    except Exception as e:
        print(f"team stats unavailable ({e})")

    sp_season_cache = {}
    def sp_season(pid):
        if not pid or pid in sp_season_cache:
            return sp_season_cache.get(pid)
        out = None
        try:
            d = get_json(SP_SEASON.format(pid=pid, y=datetime.now(ET).year), tries=2)
            for st in d.get("stats", []):
                for sp in st.get("splits", []):
                    stat = sp.get("stat") or {}
                    out = dict(era=float(stat.get("era") or 0) or None,
                               whip=float(stat.get("whip") or 0) or None,
                               ip=ip_to_float(stat.get("inningsPitched")))
        except Exception:
            pass
        sp_season_cache[pid] = out
        return out

    LG_DRIFT = league_drift()
    if LG_DRIFT != 1.0:
        print(f"league HR drift factor (trailing 14d): {LG_DRIFT:.3f}")
    targets, games_out = [], []
    for g in slate.get("games", []):
        away, home = g["away"], g["home"]
        wx = 1.0 if g.get("dome") else clamp(1 + (g.get("hr", 0) or 0) / 100 * 0.40, 0.85, 1.15)
        # v4: weather coeff 0.75 -> 0.40, clamp +/-15% — week 3 factor grading
        # showed the biggest per-batter weather boosts hitting 12% vs 23.7% stated
        # (n=25): game-level weather is real, stacking it per batter double-counts
        um, um_n = ump_mult(g.get("ump"), umps_all, umps_pro)
        ump_name = (g.get("ump") or {}).get("name")
        p_away = (g.get("pitchers") or {}).get("away")   # away SP faces HOME batters
        p_home = (g.get("pitchers") or {}).get("home")   # home SP faces AWAY batters
        sp_for_home, spn_h = sp_mult(p_away)
        sp_for_away, spn_a = sp_mult(p_home)
        id_away = ((g.get("pitchers") or {}).get("away") or {}).get("id")
        id_home = ((g.get("pitchers") or {}).get("home") or {}).get("id")

        exp_hr = 0.0
        game_lineup = {}
        for team, opp, spm, sp_name, spid in (
                (away, home, sp_for_away, (p_home or {}).get("name"), id_home),
                (home, away, sp_for_home, (p_away or {}).get("name"), id_away)):
            roster = (hitters.get(team) or {}).get("players", {})
            lu = lineups.get(team)
            cand = []
            for pid, pl in roster.items():
                adj, ab, hr = batter_rate(pl.get("g", []))
                if adj is None:
                    continue
                order = lu.get(str(pid)) if lu else None
                if lu and order is None:
                    continue                     # lineup posted, batter not in it
                cand.append((pid, pl, adj, ab, hr, order))
            if not lu:
                # no lineup yet — projected nine = top 9 by 3-season AB
                cand = sorted(cand, key=lambda c: -c[3])[:9]
            for pid, pl, adj, ab, hr, order in cand:
                pa = 4.65 - 0.13 * (order - 1) if order else PA_PER_GAME
                env = (wx * um * spm) ** 0.75   # damp stacked env factors (calibration)
                rate = adj * env * LG_DRIFT
                prob = 1 - (1 - min(rate, 0.18)) ** pa
                prob_pct = calibrate(round(prob * 100, 1))
                exp_hr += prob_pct / 100
                o = odds_by_player.get(norm_name(pl["name"]))
                # de-vig at x0.87 — one-sided HR markets carry ~13pt vig, not 7
                fair = round(o["implied"] * 0.87, 1) if o and o.get("implied") else None
                if o and o.get("implied") is not None:
                    # market anchor at 40% — week 1 the books' Brier edged ours
                    prob_pct = round(0.60 * prob_pct + 0.40 * o["implied"], 1)
                edge = round(prob_pct - fair, 1) if fair is not None else None
                row = dict(
                    _bid=pid, _spid=spid,
                    _adj=adj, _env=dict(wx=wx, um=um, spm=spm), _pa=pa,
                    player=pl["name"], team=team, opp=opp,
                    game=f"{away} @ {home}",
                    prob=prob_pct, order=order,
                    f=dict(bat=round(adj / LG_HR_AB, 2), wx=round(wx, 2),
                           ump=round(um, 2), sp=round(spm, 2)),
                    seasons=f"{hr} HR / {ab} AB (3 seasons)",
                    sp=sp_name,
                    price=o["price"] if o else None,
                    implied=o["implied"] if o else None,
                    books=o["books"] if o else 0,
                    fair=fair, edge=edge, value=False)
                targets.append(row)
                # Lineups tab: same dict object, so BvP/alt updates flow through
                game_lineup.setdefault(team, []).append(row)
            # lineup members with no 3-season sample (rookies / call-ups):
            # they still get a row — a number for everybody, honestly labeled
            if lu:
                seen = {str(p[0]) for p in cand}
                for pid, slot in lu.items():
                    if pid in seen:
                        continue
                    nm = ((roster.get(pid) or {}).get("name")
                          or (lu_names.get(team) or {}).get(pid))
                    if nm:
                        game_lineup.setdefault(team, []).append(dict(
                            player=nm, team=team, opp=opp, order=slot,
                            prob=None, sp=sp_name,
                            note="under 50 AB in our 3-season sample"))

        # ---- runs projection (partner's Combined page, our shrinkage) ----
        runs_proj = None
        wx_runs = clamp(1 + ((g.get("mlb") or {}).get("runs", 0) or 0) / 100 * 0.5,
                        0.85, 1.18) if not g.get("dome") else 1.0
        ump_r = 1.0
        if umps_pro and ump_name and ump_name in umps_pro.get("umps", {}):
            u = umps_pro["umps"][ump_name]
            shr = (u["rpg"] * u["n"] + umps_pro["league"]["rpg"] * 150) / (u["n"] + 150)
            ump_r = clamp(shr / umps_pro["league"]["rpg"], 0.95, 1.05)
        sides = {}
        for team, opp_spid, opp_sp_name in ((away, id_home, (p_home or {}).get("name")),
                                            (home, id_away, (p_away or {}).get("name"))):
            off = team_off.get(team)
            if not off:
                continue
            sps = sp_season(opp_spid)
            if sps and sps.get("era") and sps.get("ip"):
                era_s = (sps["era"] * sps["ip"] + LG_ERA * 40) / (sps["ip"] + 40)
            else:
                era_s = LG_ERA
            # exponent 0.6: the starter covers ~60% of innings — a full ERA
            # ratio double-counts what season R/G already includes
            sp_factor = clamp((era_s / LG_ERA) ** 0.6, 0.80, 1.25)
            proj = off["rg"] * sp_factor * wx_runs * ump_r
            sides[team] = dict(proj=round(proj, 1), rg=off["rg"], ops=off.get("ops"),
                               oppSp=opp_sp_name,
                               oppEra=sps.get("era") if sps else None,
                               oppWhip=sps.get("whip") if sps else None)
        if len(sides) == 2:
            total = round(sides[away]["proj"] + sides[home]["proj"], 1)
            line = g.get("total") if g.get("lineSource") == "book" else None
            diff = round(total - line, 1) if line else None
            lean = None
            if diff is not None and abs(diff) >= 1.0:
                lean = "OVER" if diff > 0 else "UNDER"
            runs_proj = dict(away=sides[away], home=sides[home], total=total,
                             line=line, diff=diff, lean=lean,
                             wxRuns=round(wx_runs, 2), umpRuns=round(ump_r, 2))

        park_avg = g.get("hrPark") or 0
        vs_park = round((exp_hr / park_avg - 1) * 100) if park_avg else None
        games_out.append(dict(
            away=away, home=home, time=g.get("time"), gamePk=g.get("gamePk"),
            ump=ump_name, umpMult=round(um, 3), umpN=um_n,
            weatherHr=g.get("hr", 0), dome=bool(g.get("dome")),
            spAway=(p_away or {}).get("name"), spHome=(p_home or {}).get("name"),
            spAwayHr9=((p_away or {}).get("all") or {}).get("hr9"),
            spHomeHr9=((p_home or {}).get("all") or {}).get("hr9"),
            expHr=round(exp_hr, 2), parkHr=park_avg, vsPark=vs_park,
            lineups=bool(lineups.get(away) or lineups.get(home)),
            luPosted=dict(away=bool(lineups.get(away)), home=bool(lineups.get(home))),
            lineup={t: sorted(rows, key=lambda r: (r.get("order") or 99, -(r.get("prob") or 0)))
                    for t, rows in game_lineup.items()},
            runs=runs_proj))

    # ---- with-ump splits (display only, never a multiplier) ----
    n_split_calls = 0
    for gout, g in zip(games_out, slate.get("games", [])):
        ump = gout["ump"]
        away, home = gout["away"], gout["home"]
        if not ump or not (by_dh or by_pk):
            continue
        if not (lineups.get(away) and lineups.get(home)):
            continue                      # wait for both lineups (evening builds)
        splits = dict(seasons=f"{SPLIT_SEASONS[0]}-{SPLIT_SEASONS[-1]}",
                      batters={}, pitchers=[], bvp={})
        sp_starts = {}
        for side, spid, spname in (("away", ((g.get("pitchers") or {}).get("away") or {}).get("id"),
                                    gout["spAway"]),
                                   ("home", ((g.get("pitchers") or {}).get("home") or {}).get("id"),
                                    gout["spHome"])):
            if not spid:
                continue
            rows = game_log(spid, "pitching")
            n_split_calls += len(SPLIT_SEASONS)
            sp_starts[side] = {r["pk"] for r in rows if r["pk"]}
            with_u = match_ump(rows, ump, by_dh, by_pk)
            if with_u:
                splits["pitchers"].append(dict(name=spname, side=side, **agg_pit(with_u)))
        for team, opp_side in ((away, "home"), (home, "away")):
            lu = lineups.get(team) or {}
            names = lu_names.get(team) or {}
            roster = (hitters.get(team) or {}).get("players", {})
            brows, vrows = [], []
            for pid in lu:
                nm = (roster.get(pid) or {}).get("name") or names.get(pid)
                if not nm:
                    continue
                rows = game_log(pid, "hitting")
                n_split_calls += len(SPLIT_SEASONS)
                with_u = match_ump(rows, ump, by_dh, by_pk)
                if with_u:
                    brows.append(dict(name=nm, order=lu[pid], **agg_bat(with_u)))
                opp_pks = sp_starts.get(opp_side) or set()
                three = [r for r in with_u if r["pk"] in opp_pks]
                if three:
                    vrows.append(dict(name=nm, **agg_bat(three)))
            brows.sort(key=lambda b: (-b["hr"], -b["g"]))
            vrows.sort(key=lambda b: (-b["hr"], -b["g"]))
            if brows:
                splits["batters"][team] = brows
            if vrows:
                splits["bvp"][team] = vrows
        if splits["batters"] or splits["pitchers"]:
            gout["splits"] = splits
    if n_split_calls:
        print(f"with-ump splits: {n_split_calls} gameLog calls")

    # ---- K props: projected strikeouts for each probable starter ----
    ks_odds = {}
    for pg in props.get("games", []):
        for o in pg.get("ks", []):
            ks_odds.setdefault(norm_name(o["player"]), o)
    kprops = []
    LG_UMP_SO = (umps_all.get("_league") or {}).get("so") or 17.1
    def ump_k_mult(ump_name):
        """Zone signal: shrunk ump strikeout environment vs league, capped ±6%.
        A wide-zone ump is worth real Ks — his app tracks this, ours now prices it."""
        u = umps_all.get(ump_name or "")
        if not u or not u.get("so") or not u.get("n"):
            return 1.0
        shrunk = (u["so"] * u["n"] + LG_UMP_SO * 150) / (u["n"] + 150)
        return clamp(shrunk / LG_UMP_SO, 0.94, 1.06)
    for g in slate.get("games", []):
        wxk = (g.get("ks", 0) or 0)
        ump_nm = (g.get("ump") or {}).get("name")
        kmult = ump_k_mult(ump_nm)
        for side, team, opp in (("away", g["away"], g["home"]), ("home", g["home"], g["away"])):
            p = (g.get("pitchers") or {}).get(side)
            if not p or not p.get("all"):
                continue
            a = p["all"]
            ip, n, k9 = a.get("ip", 0), a.get("n", 0), a.get("k9")
            if not ip or not n or k9 is None:
                continue
            k9s = (k9 * ip + 8.5 * 60) / (ip + 60)              # shrink K/9 toward league
            ip_ps = (ip / n * n + 5.3 * 4) / (n + 4)            # shrink IP/start toward 5.3
            proj = k9s * ip_ps / 9 * (1 + wxk / 100 * 0.5) * kmult
            proj = round(clamp(proj, 2.5, 11.0), 1)
            o = ks_odds.get(norm_name(p["name"]))
            line = o["line"] if o else None
            diff = round(proj - line, 1) if line is not None else None
            # v4: lean calls RETIRED 8/25 — 27/57 (47%) over 20 graded nights.
            # Projection and line stay on the card; no call until the K model
            # is rebuilt. The 57-call public record stands on the Record tab.
            lean = None
            kprops.append(dict(pitcher=p["name"], team=team, opp=opp,
                               game=f"{g['away']} @ {g['home']}",
                               proj=proj, ipStart=round(ip_ps, 1), k9=round(k9s, 1),
                               wxK=wxk, ump=ump_nm,
                               umpK=round((kmult - 1) * 100, 1) if kmult != 1.0 else 0,
                               line=line,
                               over=o["over"] if o else None,
                               under=o["under"] if o else None,
                               lean=lean, diff=diff))
    kprops.sort(key=lambda k: (k["line"] is None, -(abs(k["diff"]) if k["diff"] is not None else 0), -k["proj"]))

    targets.sort(key=lambda t: -t["prob"])
    # ---- BvP pass: career vs tonight's SP, top of the board only ----
    for t in targets[:70]:
        m, rawtxt = bvp_mult(t.pop("_bid", None), t.pop("_spid", None))
        e = t.pop("_env"); adj = t.pop("_adj"); pa = t.pop("_pa")
        t["f"]["bvp"] = round(m, 2) if m else None
        t["bvpRaw"] = rawtxt
        # v4: BvP no longer moves the probability — flagged targets graded 1/15
        # (6.7% vs 22.5% stated). Archived in f.bvp and shown as context only.
        env = (e["wx"] * e["um"] * e["spm"]) ** 0.75
        rate = adj * env * LG_DRIFT
        prob = 1 - (1 - min(rate, 0.18)) ** pa
        p = calibrate(round(prob * 100, 1))
        if t.get("implied") is not None:
            p = round(0.60 * p + 0.40 * t["implied"], 1)
        t["prob"] = p
        if t.get("fair") is not None:
            t["edge"] = round(p - t["fair"], 1)
        # 2+ HR: binomial P(X>=2) over 4 PA, derived from the SAME calibrated
        # probability we display (keeps 1+ and 2+ internally consistent)
        r2 = 1 - (1 - p / 100) ** 0.25
        p2 = 1 - (1 - r2) ** 4 - 4 * r2 * (1 - r2) ** 3
        t["p2"] = round(p2 * 100, 1)
        o = odds_by_player.get(norm_name(t["player"]))
        if o and o.get("alt"):
            t["alt"] = o["alt"]
        time.sleep(0.25)
    for t in targets[70:]:
        for k in ("_bid", "_spid", "_env", "_adj", "_pa"):
            t.pop(k, None)
    targets.sort(key=lambda t: -t["prob"])
    # VALUE flags: v2 thresholds (edge >= 5 vs x0.87 de-vig) — week 1's 3-pt
    # flags went 1-7; most of that "edge" was just understated vig
    flagged = sorted([t for t in targets
                      if t["edge"] is not None and t["edge"] >= 5
                      and t["books"] >= 3 and (t["price"] or 0) >= 150],
                     key=lambda t: -t["edge"])[:5]
    for t in flagged:
        t["value"] = True
    # v4: sub-20% targets graded 4/36 (11.1%) over 20 nights — filler, cut.
    top = [t for t in targets if t["prob"] >= 20]
    if len(top) < 8:
        top = targets[:8]     # cold-slate guard: never an empty card
    top = top[:40]

    # ---- intel feed ----
    intel = []
    real = [go for go in games_out if go["expHr"]]
    if real:
        b = max(real, key=lambda go: go["expHr"])
        bits = []
        if b["ump"] and b.get("umpMult") not in (None, 1.0):
            bits.append(f"ump {'+' if b['umpMult'] >= 1 else ''}{round((b['umpMult']-1)*100)}%")
        bits.append(f"weather {'+' if (b['weatherHr'] or 0) >= 0 else ''}{b['weatherHr']}%")
        intel.append(dict(icon="💣", tag="TONIGHT", game=f"{b['away']} @ {b['home']}",
                          title=f"{b['away']} @ {b['home']} is tonight's top HR environment",
                          text=f"{b['expHr']} expected HRs from our batter-by-batter model — "
                               + ", ".join(bits),
                          stat=f"{b['expHr']} exp HR"))
    for go in games_out:
        w = go.get("weatherHr") or 0
        if go["dome"] or abs(w) < 15:
            continue
        up = w > 0
        intel.append(dict(icon="☀️" if up else "🌬️", tag="WEATHER",
                          game=f"{go['away']} @ {go['home']}",
                          title=f"Weather {'helping' if up else 'hurting'} hitters in "
                                f"{go['away']} @ {go['home']}",
                          text=f"Similar-weather games at this park ran {w:+d}% on HRs vs the "
                               f"park norm — {'warm temps or outward wind' if up else 'cool air or wind knocking balls down'} tonight",
                          stat=f"{w:+d}%"))
    if umps_pro:
        lg = umps_pro["league"]["hrpg"]
        for go in games_out:
            u = umps_pro["umps"].get(go["ump"] or "")
            if not u:
                continue
            pk = u["parks"].get(go["home"])
            if pk and pk[0] >= 5:
                v_lg = round((pk[1] / lg - 1) * 100)
                v_car = round((pk[1] / u["hrpg"] - 1) * 100) if u["hrpg"] else 0
                if abs(v_lg) >= 15:
                    intel.append(dict(icon="🎯", tag="UMP × PARK",
                                      game=f"{go['away']} @ {go['home']}",
                                      title=f"{go['ump']} at {go['home']}: {pk[1]} HR/game in {pk[0]} games",
                                      text=f"{v_lg:+d}% vs league avg · {v_car:+d}% vs his own career average behind the plate here",
                                      stat=f"{pk[1]} HR/g"))
            if u["n"] >= 30 and abs(u["last5"]["vscareer"]) >= 15:
                hot = u["last5"]["vscareer"] > 0
                intel.append(dict(icon="🔥" if hot else "❄️", tag="STREAK",
                                  game=f"{go['away']} @ {go['home']}",
                                  title=f"{go['ump']} is running {'hot' if hot else 'cold'} heading into tonight",
                                  text=f"{u['last5']['hrpg']} HR/game over his last 5 — "
                                       f"{u['last5']['vscareer']:+.0f}% vs his career {u['hrpg']} HR/game",
                                  stat=f"{u['last5']['vscareer']:+.0f}%"))
        m = umps_pro.get("meta") or {}
        if m.get("top"):
            intel.append(dict(icon="👀", tag="LEAGUE", game=None,
                              title=f"{m['top'][0]} calls the most HR-friendly games of any regular ump",
                              text=f"{m['top'][1]:+.1f}% vs league average across our {umps_pro['seasons']} dataset — check the board when he's posted",
                              stat=f"{m['top'][1]:+.1f}%"))
        if m.get("low"):
            intel.append(dict(icon="🛑", tag="LEAGUE", game=None,
                              title=f"{m['low'][0]} is the most HR-suppressive regular ump in our dataset",
                              text=f"{m['low'][1]:+.1f}% vs league average — fade HR props when he's behind the plate",
                              stat=f"{m['low'][1]:+.1f}%"))
        if m.get("record"):
            r = m["record"]
            dd = f"{r['d'][:4]}-{r['d'][4:6]}-{r['d'][6:]}"
            intel.append(dict(icon="🚀", tag="RECORD", game=None,
                              title=f"Dataset record: {r['hr']} HRs in a single game",
                              text=f"{r['matchup']} on {dd} — {r['ump']} behind the plate. Highest single-game total in {m['games']:,} tracked games",
                              stat=f"{r['hr']} HR"))
        intel.append(dict(icon="📊", tag="DATASET", game=None,
                          title=f"The PRO ump layer tracks {m.get('games', 0):,} games across {umps_pro['seasons']}",
                          text=f"{m.get('hrs', 0):,} home runs logged · {m.get('umps', 0)} umpires · league baseline {lg} HR/game",
                          stat=f"{m.get('games', 0):,} games"))
    tot_leans = [go for go in games_out if (go.get("runs") or {}).get("lean")]
    for go in tot_leans[:3]:
        r = go["runs"]
        intel.append(dict(icon="📈" if r["lean"] == "OVER" else "📉", tag="TOTALS",
                          game=f"{go['away']} @ {go['home']}",
                          title=f"Our total says {r['lean']} in {go['away']} @ {go['home']}",
                          text=f"Projected {r['total']} runs vs the {r['line']} line ({r['diff']:+.1f}) — "
                               f"offense × opposing SP × weather × ump",
                          stat=f"{r['diff']:+.1f}"))

    parts = []
    if top:
        b = top[0]
        parts.append(f"{b['player']} ({b['team']}) leads the board — {b['prob']}% HR chance"
                     + (f", priced {b['price']:+d} (implied {b['implied']}%)." if b["price"] else "."))
    if flagged:
        v = flagged[0]
        parts.append(f"Best value: {v['player']} {v['price']:+d} — our number says "
                     f"{v['prob']}% vs {v['fair']}% fair implied (+{v['edge']} pts). "
                     f"{len(flagged)} value flag{'s' if len(flagged)>1 else ''} tonight.")
    else:
        parts.append("No value flags tonight — the books are priced tight to our numbers.")
    kleans = [k for k in kprops if k["lean"]]
    if kleans:
        kk = kleans[0]
        parts.append(f"K props: {kk['pitcher']} projects {kk['proj']} Ks vs a {kk['line']} line — lean {kk['lean']}.")

    payload = dict(generated=datetime.now(ET).strftime("%Y-%m-%d %H:%M ET"),
                   date=datetime.now(ET).strftime("%Y-%m-%d"),
                   oddsGenerated=props.get("generated"),
                   brief=" ".join(parts), games=games_out, targets=top,
                   kprops=kprops[:24], intel=intel[:20])
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(payload, f, separators=(",", ":"))

    # ---- free-side teaser feed (site/teaser.json) ----
    # Publishes ONLY the #1 target in the clear. The rest of the card ships as
    # salted FNV-1a name hashes + rank + price, so the free page's live ticker
    # can announce "PRO's #7 target just homered (+520)" without leaking the
    # board (names/probs are never in the free payload).
    def fnv(s):
        h = 0x811c9dc5
        for ch in s:
            h = ((h ^ ord(ch)) * 0x01000193) & 0xffffffff
        return format(h, "08x")
    salt = datetime.now(ET).strftime("%Y%m%d")
    t1 = top[0] if top else None
    teaser = dict(
        generated=payload["generated"], date=payload["date"],
        top1=None if not t1 else dict(player=t1["player"], team=t1["team"],
                                      game=t1["game"], prob=t1["prob"],
                                      price=t1["price"], implied=t1["implied"],
                                      value=t1["value"]),
        counts=dict(targets=len(top), priced=sum(1 for t in top if t["price"] is not None),
                    value=len(flagged), games=len(games_out)),
        expTop=None if not games_out else max(
            (dict(game=f"{go['away']} @ {go['home']}", exp=go["expHr"])
             for go in games_out if go["expHr"]), key=lambda x: x["exp"], default=None),
        salt=salt,
        tlist=[dict(r=i + 1, h=fnv(salt + norm_name(t["player"])),
                    price=t["price"], value=t["value"])
               for i, t in enumerate(top)])
    with open(os.path.join(ROOT, "site", "teaser.json"), "w") as f:
        json.dump(teaser, f, separators=(",", ":"))
    print(f"Wrote site/teaser.json (#1: {t1['player'] if t1 else '—'})")

    # archive tonight's card for future grading
    os.makedirs(PRED_DIR, exist_ok=True)
    dstr = datetime.now(ET).strftime("%Y%m%d")
    slim = [dict(player=t["player"], team=t["team"], game=t["game"], prob=t["prob"],
                 price=t["price"], implied=t["implied"], value=t["value"],
                 f=t.get("f"))
            for t in top[:20]]
    kslim = [dict(pitcher=k["pitcher"], game=k["game"], proj=k["proj"],
                  line=k["line"], lean=k["lean"])
             for k in kprops if k.get("line") is not None]
    # game-level projections: graded nightly as avg error / within 1 / within 2,
    # plus the ump-reliability check (did the ump's tendency hold tonight?)
    gslim = []
    for go in games_out:
        if not go.get("gamePk") or not go.get("expHr"):
            continue
        uv = None
        if umps_pro and go.get("ump") and go["ump"] in umps_pro.get("umps", {}):
            uv = umps_pro["umps"][go["ump"]]["vslg"]
        gslim.append(dict(pk=go["gamePk"], m=f"{go['away']}@{go['home']}",
                          expHr=go["expHr"], ump=go.get("ump"), umpVslg=uv))
    # Freeze the card once the slate is under way. Refreshes before first
    # pitch are fine (nothing has happened yet); a 5 PM ET rebuild must not
    # reshuffle targets after the afternoon games are already final.
    now_et = datetime.now(ET)
    now_hm = now_et.hour * 100 + now_et.minute
    started = any((g.get("sortTime") or 9999) <= now_hm
                  for g in slate.get("games", []))
    save_locked(os.path.join(PRED_DIR, f"{dstr}.json"),
                dict(d=dstr, targets=slim, kprops=kslim, games=gslim),
                started, label="MLB archive")

    with_odds = sum(1 for t in top if t["price"] is not None)
    n_splits = sum(1 for go in games_out if go.get("splits"))
    print(f"Wrote {OUT}: {len(top)} targets ({with_odds} with live prices, "
          f"{len(flagged)} VALUE flags), {len(games_out)} games, "
          f"{n_splits} with-ump split panels, {len(intel)} intel cards")

if __name__ == "__main__":
    main()
