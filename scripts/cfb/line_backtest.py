#!/usr/bin/env python3
"""Backtest of the line-play trench edge (scripts/cfb/linemodel.py) and of the
roster-weight edge it replaces, on the same FBS-vs-FBS team-games.

The claim under test is the one the board is graded on: a flagged offense's
yards per carry beats that week's FBS median (a fade: lands below it).

Honest protocol: every game is rated only from games played before it, and
each test season's scaling and cut-offs come from EARLIER seasons only
(2022 is rated with numbers from 2019+2021, 2023 with 2019-2022, ...). A team
is a target above the earlier seasons' 90th-percentile edge and a fade below
their 10th.

Also reported, because it is the part a matchup adds on top of team quality:
how often an offense beats ITS OWN season average, by the run defense it faces.

Reads  data/cfb/line_games.csv.gz, data/cfb/line_weights.json
Writes data/cfb/line_backtest.json (receipts for the page)
       data/cfb/line_model.json    (scaling + cut-offs the weekly board uses)
No third-party dependencies.     python scripts/cfb/line_backtest.py
"""
import json, os, statistics, sys

sys.path.insert(0, os.path.dirname(__file__))
import linemodel as lm      # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
DATA = os.path.join(ROOT, "data", "cfb")
PREV = {2021: 2019, 2022: 2021, 2023: 2022, 2024: 2023, 2025: 2024, 2026: 2025}
TEST = [2022, 2023, 2024, 2025, 2026]


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * p))]


def rate(rows):
    return round(sum(rows) / len(rows), 3) if rows else None


def main():
    rows = lm.load_csv(os.path.join(DATA, "line_games.csv.gz"))
    weights = json.load(open(os.path.join(DATA, "line_weights.json")))
    med = {}
    for r in rows:
        med.setdefault((r["season"], r["week"]), []).append(r["ypc"])
    med = {k: statistics.median(v) for k, v in med.items()}
    rated = {}
    for r, raw in lm.replay(rows, sorted(set(PREV) | {2019}), PREV):
        raw["hit"] = r["ypc"] > med[(r["season"], r["week"])]
        raw["ypc"] = r["ypc"]
        w = weights.get(str(r["season"]), {})
        a, b = w.get(r["team"]), w.get(r["opp"])
        raw["wdiff"] = a[0] - b[1] if a and b and a[0] and b[1] else None
        rated.setdefault(r["season"], []).append(raw)

    out, seasons, tg, fd, lad, own, wq = [], [], [], [], {}, {}, {}
    for ts in TEST:
        past = [x for s, v in rated.items() if s < ts for x in v]
        sd = lm.sds(past)
        ps = [lm.score(x, sd) for x in past]
        hi, lo = pct(ps, 0.9), pct(ps, 0.1)
        qs = [pct(ps, q) for q in (0.2, 0.4, 0.6, 0.8)]
        dsd = {k: sd["d"][k] for k in lm.KEYS}
        pd = [sum(x["d_" + k] / dsd[k] for k in lm.KEYS) for x in past]
        dq = [pct(pd, q) for q in (0.1, 0.9)]
        pw = [x["wdiff"] for x in past if x["wdiff"] is not None]
        wqs = [pct(pw, q) for q in (0.2, 0.8)]
        t, f = [], []
        for x in rated[ts]:
            s = lm.score(x, sd)
            if s >= hi:
                t.append(x["hit"])
            if s <= lo:
                f.append(not x["hit"])
            q = sum(s > c for c in qs)
            lad.setdefault(q, []).append(x)
            d = sum(x["d_" + k] / dsd[k] for k in lm.KEYS)
            if d >= dq[1] or d <= dq[0]:
                own.setdefault("soft" if d >= dq[1] else "tough", []).append(x["ypc"] > x["own"])
            if x["wdiff"] is not None and (x["wdiff"] >= wqs[1] or x["wdiff"] <= wqs[0]):
                wq.setdefault("top" if x["wdiff"] >= wqs[1] else "bottom", []).append(
                    x["hit"] if x["wdiff"] >= wqs[1] else not x["hit"])
        tg += t
        fd += f
        seasons.append(dict(season=ts, games=len(rated[ts]), targets=len(t), targetHit=rate(t),
                            fades=len(f), fadeHit=rate(f)))
        print(f"{ts}: {len(rated[ts])} team-games · targets {sum(t)}/{len(t)} ({rate(t)}) · "
              f"fades {sum(f)}/{len(f)} ({rate(f)})")

    names = ["Q1 worst edge", "Q2", "Q3", "Q4", "Q5 best edge"]
    ladder = [dict(label=names[q], n=len(v), ypc=round(statistics.mean(x["ypc"] for x in v), 2),
                   beat=rate([x["hit"] for x in v])) for q, v in sorted(lad.items())]
    res = dict(seasons=TEST, n=sum(s["games"] for s in seasons),
               targets=dict(n=len(tg), w=sum(tg), rate=rate(tg)),
               fades=dict(n=len(fd), w=sum(fd), rate=rate(fd)),
               bySeason=seasons, ladder=ladder,
               ownNorm=dict(soft=dict(n=len(own["soft"]), rate=rate(own["soft"])),
                            tough=dict(n=len(own["tough"]), rate=rate(own["tough"]))),
               weightEdge=dict(top=dict(n=len(wq["top"]), rate=rate(wq["top"])),
                               bottom=dict(n=len(wq["bottom"]), rate=rate(wq["bottom"]))))
    json.dump(res, open(os.path.join(DATA, "line_backtest.json"), "w"), indent=1)
    print(f"targets {res['targets']} · fades {res['fades']}")
    print(f"vs own average: {res['ownNorm']} · old weight edge: {res['weightEdge']}")

    # what the weekly board uses for the current season: everything known today
    done = [x for s, v in rated.items() if s < max(rated) for x in v]
    sd = lm.sds(done)
    ps = [lm.score(x, sd) for x in done]
    model = dict(builtFrom=sorted(s for s in rated if s < max(rated)), k0=lm.K0, home=lm.HOME,
                 sd={side: {k: round(v, 5) for k, v in d.items()} for side, d in sd.items()},
                 cuts=dict(fade=round(pct(ps, 0.1), 3), target=round(pct(ps, 0.9), 3),
                           quintiles=[round(pct(ps, q), 3) for q in (0.2, 0.4, 0.6, 0.8)]))
    json.dump(model, open(os.path.join(DATA, "line_model.json"), "w"), indent=1)
    print(f"model: {model}")


if __name__ == "__main__":
    main()
