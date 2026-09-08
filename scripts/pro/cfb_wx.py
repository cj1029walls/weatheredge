#!/usr/bin/env python3
"""DFSRADAR PRO — CFB Wind Factor -> site/pro/cfb_wx.json

The free radar answers "what has this venue done in weather like tonight's?"
one game at a time. This answers the question underneath it: across sixteen
seasons of Power 4 home games, what does wind ACTUALLY do to a football game?

Method, in one paragraph. Every outdoor game in data/cfb/venues_history.json is
sorted into a wind-speed band by its kickoff-hour wind. Each band reports its
own mean for scoring, passing yards, rushing yards, completion rate and
turnovers, against the pooled outdoor baseline, together with a z-score so a
reader can see which gaps are actually distinguishable from noise. Every figure
on both sides of that comparison is era-normalized first, because offense in
2010 and offense in 2025 are not the same game: a band that happens to hold
more old games would otherwise read as a wind effect.

Two things this deliberately refuses to claim.

First, totals and sides. The history carries no closing lines (CFBD does not
publish them back to 2010), so there is no honest ATS or over/under claim to
make, and none is made.

Second, and less obviously: a per-VENUE wind effect. It is the table everyone
in this space ships, and it does not survive testing. Shuffling the wind labels
inside each stadium and recomputing produces a spread of venue effects as wide
as the real one (see the venue_test block in the output, which carries the
receipts and is rendered on the page). At fifteen-to-forty games a side, a
stadium's windy-minus-calm scoring gap is noise, and ranking stadiums by it
would be selling a leaderboard of coin flips. What IS well-powered per venue is
the wind distribution itself — no outcome involved — so the board reports how
unusual a forecast is FOR THAT STADIUM instead, and leaves the effect size to
the league-wide ladder where the sample can carry it.

Era normalization is imported from the weekly build rather than reimplemented,
so the two pages can never drift into quoting different baselines.

No third-party dependencies.
"""
import functools, json, math, os, random, statistics, sys
from datetime import datetime
from zoneinfo import ZoneInfo

print = functools.partial(print, flush=True)

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
HISTORY = os.path.join(ROOT, "data", "cfb", "venues_history.json")
FREE = os.path.join(ROOT, "site", "cfb", "data.json")
OUT = os.path.join(ROOT, "site", "pro", "cfb_wx.json")
ET = ZoneInfo("America/New_York")

# Shared era machinery. Importing beats copying: a change to how a season is
# weighted has to land on both pages at once or they quote different numbers.
sys.path.insert(0, os.path.join(ROOT, "scripts", "cfb"))
import weekly_build as wb  # noqa: E402

# Bands are wide on purpose. Kickoff wind is a single hourly reading at a
# single point, so slicing it finer than this is precision the measurement does
# not have. The top band is open-ended: 22+ mph is only twenty games in sixteen
# seasons, and a band that thin is better folded in than reported alone.
BANDS = [
    ("Calm",     0,  6,  "Flags hang. Nothing in the forecast is touching the ball."),
    ("Breezy",   6,  11, "Noticeable at the top of a punt, not much else."),
    ("Blustery", 11, 16, "Deep balls start dying and the completion rate goes with them."),
    ("Windy",    16, 99, "The passing game comes apart. This is the band that matters."),
]

# Reported metrics, in board order. FUMBLES is carried by the history but not
# shown: fumbles are far too noisy a series to read at these sample sizes.
SHOW = [
    ("pts", "SCORING",      "pts", 0),
    ("pa",  "PASSING YDS",  "yds", 0),
    ("ru",  "RUSHING YDS",  "yds", 0),
    ("cp",  "COMPLETION %", "%",   1),
    ("to",  "TURNOVERS",    "",    1),
]

MIN_BAND_N = 60      # a band thinner than this is not reported at all
SIG_Z = 2.0          # |z| at or above this is marked as distinguishable
VENUE_CUT = 11       # the windy/calm split used by the venue shuffle test
MIN_VENUE_N = 15     # a venue needs this many games on BOTH sides of that cut
SHUFFLES = 400
SEED = 7             # fixed so the published receipts are reproducible


def band_of(w):
    for name, lo, hi, _note in BANDS:
        if lo <= w < hi:
            return name
    return None


def adj(game, key):
    """One game's value for a metric, era-normalized exactly the way the free
    radar normalizes it, so both pages sit on one set of units."""
    if key == "pts":
        return game.get("epts", game.get("pts"))
    v = game.get(key)
    if v is None:
        return None
    return v * (wb._ERA_CACHE.get(key) or {}).get(wb._season_of(game["d"]), 1.0)


def series(rows, key):
    return [v for v in (adj(g, key) for g in rows) if v is not None]


def pct_rank(sorted_vals, x):
    """Share of the venue's own kickoffs at or below this wind speed."""
    if not sorted_vals:
        return None
    lo = 0
    for v in sorted_vals:
        if v <= x:
            lo += 1
        else:
            break
    return round(lo / len(sorted_vals) * 100)


def main():
    if not os.path.exists(HISTORY):
        print(f"missing {HISTORY} — nothing to build")
        return 1
    hist = json.load(open(HISTORY))
    wb.build_era(hist)

    # Outdoor venues only. A dome game's "wind" is the wind outside the roof,
    # which is not a fact about the football game.
    outdoor = {}
    for vid, v in hist.items():
        if vid.startswith("_"):
            continue
        if str(v.get("dome", "False")).lower() in ("true", "1"):
            continue
        rows = [g for g in (v.get("games") or []) if g.get("w") is not None]
        if rows:
            outdoor[vid] = (v, rows)

    pooled = [g for _v, rows in outdoor.values() for g in rows]

    base, base_var, base_n = {}, {}, {}
    for key, _l, _u, dp in SHOW:
        vals = series(pooled, key)
        if vals:
            base[key] = round(statistics.mean(vals), dp + 1)
            base_var[key] = statistics.pvariance(vals)
            base_n[key] = len(vals)

    # ---- league-wide ladder -------------------------------------------------
    bands = []
    for name, lo, hi, note in BANDS:
        rows = [g for g in pooled if lo <= g["w"] < hi]
        if len(rows) < MIN_BAND_N:
            continue
        m = {}
        for key, _l, _u, dp in SHOW:
            vals = series(rows, key)
            b = base.get(key)
            if not vals or not b:
                m[key] = None
                continue
            mean = statistics.mean(vals)
            se = math.sqrt(statistics.pvariance(vals) / len(vals)
                           + base_var[key] / base_n[key])
            z = (mean - b) / se if se else 0.0
            m[key] = {
                "avg": round(mean, dp),
                "pct": round((mean - b) / b * 100, 1),
                "n": len(vals),
                "z": round(z, 1),
                # The page never prints a percentage as a finding unless this
                # is true; below the bar it is shown greyed, as "not separable".
                "sig": abs(z) >= SIG_Z,
            }
        bands.append({
            "name": name, "lo": lo, "hi": (None if hi >= 99 else hi),
            "label": f"{name} · {lo}–{hi} mph" if hi < 99 else f"{name} · {lo}+ mph",
            "n": len(rows), "note": note, "m": m,
        })

    # ---- the venue test we ran, and failed ---------------------------------
    # Published rather than buried: it is the reason this board has no venue
    # leaderboard on it, and a reader is entitled to check the arithmetic.
    pairs = []
    for _vid, (v, rows) in outdoor.items():
        w = [x for x in (adj(g, "pts") for g in rows if g["w"] >= VENUE_CUT) if x is not None]
        c = [x for x in (adj(g, "pts") for g in rows if g["w"] < 6) if x is not None]
        if len(w) >= MIN_VENUE_N and len(c) >= MIN_VENUE_N:
            pairs.append((v.get("team"), w, c))
    venue_test = None
    if len(pairs) >= 10:
        real = [statistics.mean(w) - statistics.mean(c) for _t, w, c in pairs]
        real_sd = statistics.pstdev(real)
        rng = random.Random(SEED)
        sds = []
        for _ in range(SHUFFLES):
            ds = []
            for _t, w, c in pairs:
                pool = w + c
                rng.shuffle(pool)
                ds.append(statistics.mean(pool[:len(w)]) - statistics.mean(pool[len(w):]))
            sds.append(statistics.pstdev(ds))
        sds.sort()
        venue_test = {
            "nVenues": len(pairs),
            "cut": VENUE_CUT,
            "minN": MIN_VENUE_N,
            "shuffles": SHUFFLES,
            "realSd": round(real_sd, 2),
            "shuffledSd": round(statistics.mean(sds), 2),
            "shuffledSd95": round(sds[int(.95 * len(sds))], 2),
            "realRange": [round(min(real), 1), round(max(real), 1)],
            # True when the observed spread is inside what chance produces —
            # i.e. when there is no venue-level effect to sell.
            "indistinguishable": real_sd <= sds[int(.95 * len(sds))],
        }

    # ---- this week, placed on the ladder -----------------------------------
    # Per game: which band the forecast falls in, and how unusual that wind is
    # for that particular stadium. No per-venue effect size — see above.
    # The free feed identifies a venue by name only, and the history contains
    # two stadiums literally called "Memorial Stadium". A name that is not
    # unique gets no percentile rather than a coin-flip one.
    wind_by_name, seen = {}, {}
    for _vid, (v, rows) in outdoor.items():
        nm = v.get("name")
        if not nm:
            continue
        seen[nm] = seen.get(nm, 0) + 1
        wind_by_name[nm] = sorted(g["w"] for g in rows)
    for nm, c in seen.items():
        if c > 1:
            wind_by_name.pop(nm, None)

    games, week, updated = [], None, None
    season = None
    pro_path = os.path.join(ROOT, "site", "pro", "cfb.json")
    if os.path.exists(pro_path):
        pro = json.load(open(pro_path))
        season, week = pro.get("season"), pro.get("week")
    if os.path.exists(FREE):
        free = json.load(open(FREE))
        updated = free.get("generated")
        for g in free.get("games") or []:
            week = week or g.get("week")
            if g.get("dome"):
                continue
            w = g.get("wind")
            if w is None:
                continue
            hist_w = wind_by_name.get(g.get("stadium"))
            games.append({
                "id": g.get("id"),
                "away": g.get("away"), "home": g.get("home"),
                "awayAb": g.get("awayAb"), "homeAb": g.get("homeAb"),
                "awayColor": g.get("awayColor"), "homeColor": g.get("homeColor"),
                "stadium": g.get("stadium"), "conf": g.get("conf"), "p4": g.get("p4"),
                "day": g.get("day"), "time": g.get("time"), "sortTime": g.get("sortTime"),
                "wind": w, "windDir": g.get("windDir"), "temp": g.get("temp"),
                "sky": g.get("sky"), "skyIcon": g.get("skyIcon"),
                "band": band_of(w),
                # Percentile of this wind among that stadium's own kickoffs.
                # Well-powered because no outcome enters it.
                "vPct": pct_rank(hist_w, w) if hist_w else None,
                "vN": len(hist_w) if hist_w else None,
            })
    games.sort(key=lambda r: (-r["wind"], r.get("sortTime") or ""))

    payload = {
        "updated": updated or datetime.now(ET).strftime("%Y-%m-%d %H:%M ET"),
        "season": season, "week": week,
        "seasons": hist.get("_seasons") or hist.get("_era"),
        "nGames": len(pooled), "nVenues": len(outdoor),
        "sigZ": SIG_Z,
        "base": base,
        "metrics": [{"k": k, "label": l, "unit": u} for k, l, u, _d in SHOW],
        "bands": bands,
        "venueTest": venue_test,
        "games": games,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(payload, f, separators=(",", ":"))
    print(f"Wrote {OUT}: {len(bands)} bands over {len(pooled)} games at "
          f"{len(outdoor)} venues, {len(games)} outdoor games this week")
    if venue_test:
        print(f"  venue shuffle test: real sd {venue_test['realSd']} vs "
              f"shuffled {venue_test['shuffledSd']} (p95 {venue_test['shuffledSd95']}) "
              f"-> {'no venue effect' if venue_test['indistinguishable'] else 'VENUE EFFECT SURVIVES'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
