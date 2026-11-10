#!/usr/bin/env python3
"""The trench edge: a run-game matchup rating built from how each line has
actually played, not from what its players weigh.

For an offense going into a game we take three things it has done on the
ground so far this season -- yards per carry, rushing success rate and line
yards per carry (CollegeFootballData's line-play stat) -- and the same three
for what the defense it faces has ALLOWED. Early in a season each number is
pulled toward a prior (half last season's figure for that team, half the league
average, worth K0 games), so week 1 is last year's form and by mid-season it is
this year's. Each of the six is expressed against the league in standard
deviations and they are added up, plus a home-field bump:

    edge = z(off YPC) + z(off success) + z(off line yards)
         + z(def YPC allowed) + z(def success allowed) + z(def line yards allowed)
         + HOME * (home ? +0.5 : -0.5)

Only games played BEFORE the week being rated are used, so the same code
rates this week's board and replays history honestly (line_backtest.py).

Rows are dicts with: season, week, team, opp, home (1/0), neutral (1/0),
att, yds, rSR, ly -- the columns of data/cfb/line_games.csv.gz.
No third-party dependencies.
"""
import csv, gzip, io, statistics

KEYS = ("ypc", "rSR", "ly")
K0 = 3.0      # the prior counts as this many games
HOME = 1.0    # home field, in the same units as the six z-scores


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def clean(rows):
    """Usable team-games with ypc added (5+ carries, line stats present)."""
    out = []
    for r in rows:
        att, yds, sr, ly = num(r.get("att")), num(r.get("yds")), num(r.get("rSR")), num(r.get("ly"))
        if not att or att < 5 or yds is None or sr is None or ly is None:
            continue
        out.append(dict(season=int(r["season"]), week=int(r["week"]), team=r["team"], opp=r["opp"],
                        home=int(num(r.get("home")) or 0), neutral=int(num(r.get("neutral")) or 0),
                        att=att, yds=yds, ypc=yds / att, rSR=sr, ly=ly))
    return out


def load_csv(path):
    with gzip.open(path) as f:
        return clean(csv.DictReader(io.TextIOWrapper(f, encoding="utf-8")))


def league(rows):
    return {k: statistics.mean(r[k] for r in rows) for k in KEYS} if rows else None


def season_avgs(rows):
    """{team: {'o': {key: avg}, 'd': {key: avg}}} over a whole season (the prior)."""
    acc = {}
    for r in rows:
        for side, team in (("o", r["team"]), ("d", r["opp"])):
            a = acc.setdefault(team, {"o": {k: [] for k in KEYS}, "d": {k: [] for k in KEYS}})
            for k in KEYS:
                a[side][k].append(r[k])
    return {t: {s: {k: statistics.mean(v) for k, v in d.items() if v} for s, d in a.items()}
            for t, a in acc.items()}


class Form:
    """Every team's run-game form going into `week`, from this season's games
    before it, shrunk toward last season (prev = season_avgs of last season,
    lg = league(last season))."""

    def __init__(self, rows_before, prev, lg):
        self.lg, self.prev = lg, prev or {}
        self.now = {}
        for r in rows_before:
            for side, team in (("o", r["team"]), ("d", r["opp"])):
                a = self.now.setdefault(team, {"o": {k: [] for k in KEYS}, "d": {k: [] for k in KEYS}})
                for k in KEYS:
                    a[side][k].append(r[k])

    def value(self, team, side, key):
        """(shrunk value, games this season)"""
        xs = ((self.now.get(team) or {}).get(side) or {}).get(key) or []
        pv = ((self.prev.get(team) or {}).get(side) or {}).get(key)
        prior = self.lg[key] if pv is None else 0.5 * pv + 0.5 * self.lg[key]
        return (sum(xs) + prior * K0) / (len(xs) + K0), len(xs)

    def edge(self, off, deff, home, sd):
        """Rating for `off` running on `deff`. home: 1, 0, or 0.5 (neutral).
        sd = {'o': {key: sd}, 'd': {key: sd}}. Returns (edge, parts)."""
        total, parts = HOME * (home - 0.5), {}
        for side, team in (("o", off), ("d", deff)):
            for k in KEYS:
                v, n = self.value(team, side, k)
                total += (v - self.lg[k]) / sd[side][k]
                parts[side + "_" + k] = v
                parts[side + "_n"] = n
        return total, parts


def replay(rows, seasons, prev_of):
    """Rate every team-game of `seasons` using only what was known before it.
    prev_of: {season: prior season or None}. Yields (row, raw) where raw is the
    six centered features + home, un-scaled (the caller chooses the SDs)."""
    by_season = {}
    for r in rows:
        by_season.setdefault(r["season"], []).append(r)
    for s in seasons:
        cur = by_season.get(s) or []
        prior = by_season.get(prev_of.get(s)) or []
        lg = league(prior) or league(cur)
        prev = season_avgs(prior)
        for w in sorted({r["week"] for r in cur}):
            form = Form([r for r in cur if r["week"] < w], prev, lg)
            for r in cur:
                if r["week"] != w:
                    continue
                raw = {}
                for side, team in (("o", r["team"]), ("d", r["opp"])):
                    for k in KEYS:
                        raw[side + "_" + k] = form.value(team, side, k)[0] - lg[k]
                raw["home"] = 0.5 if r["neutral"] else r["home"]
                raw["own"] = form.value(r["team"], "o", "ypc")[0]
                yield r, raw


def sds(raws):
    return {side: {k: statistics.pstdev(x[side + "_" + k] for x in raws) or 1.0 for k in KEYS}
            for side in ("o", "d")}


def score(raw, sd):
    return (sum(raw[side + "_" + k] / sd[side][k] for side in ("o", "d") for k in KEYS)
            + HOME * (raw["home"] - 0.5))
