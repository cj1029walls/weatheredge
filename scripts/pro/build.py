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

Outputs:
  site/pro/data.json            (deployed with the site, not committed)
  data/pro/predictions/<d>.json (committed — future accuracy grading)

No third-party dependencies.
"""
import functools, json, os, sys, unicodedata
from datetime import datetime, timedelta, timezone

print = functools.partial(print, flush=True)

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
SLATE = os.path.join(ROOT, "site", "data.json")
HITTERS = os.path.join(ROOT, "data", "hitters_history.json")
UMPS = os.path.join(ROOT, "data", "umps_history.json")
PROPS = os.path.join(ROOT, "site", "pro", "props.json")
OUT = os.path.join(ROOT, "site", "pro", "data.json")
PRED_DIR = os.path.join(ROOT, "data", "pro", "predictions")

ET = timezone(timedelta(hours=-4))

# league constants + shrinkage (see spec)
LG_HR_AB = 0.032      # league HR per AB
K_BAT = 200
LG_UMP_HR = 2.40      # league HR per game
K_UMP = 150
LG_HR9 = 1.05         # league HR per 9 IP
K_SP_IP = 80
PA_PER_GAME = 4.0

def clamp(v, lo, hi):
    return max(lo, min(hi, v))

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

def ump_mult(ump, umps_all):
    if not ump or not ump.get("name") or ump["name"] not in umps_all:
        return 1.0, None
    u = umps_all[ump["name"]]
    shrunk = (u["hr"] * u["n"] + LG_UMP_HR * K_UMP) / (u["n"] + K_UMP)
    return clamp(shrunk / LG_UMP_HR, 0.88, 1.12), u["n"]

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

def main():
    for path, label in ((SLATE, "site/data.json"), (HITTERS, "hitters"), (UMPS, "umps")):
        if not os.path.exists(path):
            sys.exit(f"{label} missing — PRO build must run after the daily build.")
    slate = json.load(open(SLATE))
    hitters = json.load(open(HITTERS))
    umps_all = json.load(open(UMPS))
    props = json.load(open(PROPS)) if os.path.exists(PROPS) else {"games": []}

    # index props by normalized player name, keyed also by matchup
    odds_by_player = {}
    for pg in props.get("games", []):
        for o in pg.get("hr", []):
            odds_by_player.setdefault(norm_name(o["player"]), o)

    targets, games_out = [], []
    for g in slate.get("games", []):
        away, home = g["away"], g["home"]
        wx = 1.0 if g.get("dome") else clamp(1 + (g.get("hr", 0) or 0) / 100, 0.70, 1.40)
        um, um_n = ump_mult(g.get("ump"), umps_all)
        p_away = (g.get("pitchers") or {}).get("away")   # away SP faces HOME batters
        p_home = (g.get("pitchers") or {}).get("home")   # home SP faces AWAY batters
        sp_for_home, spn_h = sp_mult(p_away)
        sp_for_away, spn_a = sp_mult(p_home)
        games_out.append(dict(
            away=away, home=home, time=g.get("time"),
            ump=(g.get("ump") or {}).get("name"), umpMult=round(um, 3), umpN=um_n,
            weatherHr=g.get("hr", 0), dome=bool(g.get("dome")),
            spAway=(p_away or {}).get("name"), spHome=(p_home or {}).get("name")))
        for team, opp, spm, sp_name in ((away, home, sp_for_away, (p_home or {}).get("name")),
                                        (home, away, sp_for_home, (p_away or {}).get("name"))):
            roster = (hitters.get(team) or {}).get("players", {})
            for pid, pl in roster.items():
                adj, ab, hr = batter_rate(pl.get("g", []))
                if adj is None:
                    continue
                rate = adj * wx * um * spm
                prob = 1 - (1 - min(rate, 0.20)) ** PA_PER_GAME
                prob_pct = round(prob * 100, 1)
                if prob_pct > 40:      # spec sanity cap
                    prob_pct = 40.0
                o = odds_by_player.get(norm_name(pl["name"]))
                fair = round(o["implied"] * 0.93, 1) if o and o.get("implied") else None
                edge = round(prob_pct - fair, 1) if fair is not None else None
                targets.append(dict(
                    player=pl["name"], team=team, opp=opp,
                    game=f"{away} @ {home}",
                    prob=prob_pct,
                    f=dict(bat=round(adj / LG_HR_AB, 2), wx=round(wx, 2),
                           ump=round(um, 2), sp=round(spm, 2)),
                    seasons=f"{hr} HR / {ab} AB (3 seasons)",
                    sp=sp_name,
                    price=o["price"] if o else None,
                    implied=o["implied"] if o else None,
                    books=o["books"] if o else 0,
                    fair=fair, edge=edge, value=False))

    targets.sort(key=lambda t: -t["prob"])
    # VALUE flags: spec thresholds, max 5, ranked by edge
    flagged = sorted([t for t in targets
                      if t["edge"] is not None and t["edge"] >= 3
                      and t["books"] >= 3 and (t["price"] or 0) >= 150],
                     key=lambda t: -t["edge"])[:5]
    for t in flagged:
        t["value"] = True
    top = targets[:40]

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

    payload = dict(generated=datetime.now(ET).strftime("%Y-%m-%d %H:%M ET"),
                   oddsGenerated=props.get("generated"),
                   brief=" ".join(parts), games=games_out, targets=top)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(payload, f, separators=(",", ":"))

    # archive tonight's card for future grading
    os.makedirs(PRED_DIR, exist_ok=True)
    dstr = datetime.now(ET).strftime("%Y%m%d")
    slim = [dict(player=t["player"], team=t["team"], game=t["game"], prob=t["prob"],
                 price=t["price"], implied=t["implied"], value=t["value"])
            for t in top[:20]]
    with open(os.path.join(PRED_DIR, f"{dstr}.json"), "w") as f:
        json.dump(dict(d=dstr, targets=slim), f, separators=(",", ":"))

    with_odds = sum(1 for t in top if t["price"] is not None)
    print(f"Wrote {OUT}: {len(top)} targets ({with_odds} with live prices, "
          f"{len(flagged)} VALUE flags)")

if __name__ == "__main__":
    main()
