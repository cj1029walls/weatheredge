#!/usr/bin/env python3
"""DFSRADAR PRO — CFB Trench Edge grading.

Grades every archived weekly board (data/pro/cfb_predictions/<season>-w<week>.json)
against actual rushing box scores from CFBD once a week's games complete.

Grading is exactly the claim the board makes — rushing output, nothing else:
  * a TARGET (STACKED RUSH / RUSH EDGE) hits when the flagged team's YPC beats
    that week's FBS median YPC
  * a RUSH FADE hits when the flagged team's YPC lands below the median
The weekly-median benchmark is self-normalizing: a league-wide sloppy week
can't fake wins or losses. Actual att/yds/ypc are stored with every lean.

Outputs:
  data/pro/cfb_results.json     (committed — full graded history)
  site/pro/cfb_record.json      (deployed — summary + weekly detail for the page)

Runs in the CFB weekly workflow before the board build. No third-party deps.
"""
import functools, json, os, statistics, time, urllib.request

print = functools.partial(print, flush=True)

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
ARCH = os.path.join(ROOT, "data", "pro", "cfb_predictions")
RESULTS = os.path.join(ROOT, "data", "pro", "cfb_results.json")
RECORD = os.path.join(ROOT, "site", "pro", "cfb_record.json")
CFBD = "https://api.collegefootballdata.com"


def gv(d, *names):
    for n in names:
        if n in d and d[n] is not None:
            return d[n]
    return None


def fetch(url, tries=3, timeout=90):
    hdrs = {"User-Agent": "dfsradar-grade/1.0", "Accept": "application/json",
            "Authorization": f"Bearer {os.environ.get('CFBD_API_KEY','')}"}
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except Exception as e:
            if i == tries - 1:
                raise
            time.sleep(10 * (i + 1))


def week_rushing(season, week):
    """{team: {att, yds, ypc}} from the week's box scores; {} if not ready."""
    out = {}
    try:
        rows = fetch(f"{CFBD}/games/teams?year={season}&week={week}&seasonType=regular")
    except Exception as e:
        print(f"  box scores unavailable ({e})")
        return out
    for g in rows:
        for t in (gv(g, "teams") or []):
            name = gv(t, "school", "team")
            stats = {}
            for st in (gv(t, "stats") or []):
                stats[gv(st, "category")] = gv(st, "stat")
            try:
                att = float(stats.get("rushingAttempts"))
                yds = float(stats.get("rushingYards"))
            except (TypeError, ValueError):
                continue
            if name and att >= 10:
                out[name] = dict(att=int(att), yds=int(yds),
                                 ypc=round(yds / att, 2))
    return out


def grade_week(pred, rush):
    """Pure grading of one archived board against a week's rushing actuals."""
    med = statistics.median(v["ypc"] for v in rush.values())
    graded = []
    for l in pred.get("leans", []):
        act = rush.get(l["who"])
        hit = None
        if act:
            hit = (act["ypc"] > med) if l["side"] == "TARGET" else (act["ypc"] < med)
        graded.append(dict(k=l["k"], side=l["side"], who=l["who"], game=l["game"],
                           cd=l.get("cd"), act=act, hit=hit))
    return dict(medYpc=round(med, 2), nBox=len(rush), leans=graded)


def main():
    if not os.path.isdir(ARCH):
        print("no archived boards yet — nothing to grade")
        return
    results = json.load(open(RESULTS)) if os.path.exists(RESULTS) else {"weeks": {}}
    new = 0
    for f in sorted(os.listdir(ARCH)):
        if not f.endswith(".json"):
            continue
        key = f[:-5]                       # "<season>-w<week>"
        if key in results["weeks"]:
            continue
        pred = json.load(open(os.path.join(ARCH, f)))
        season, week = pred.get("season"), pred.get("week")
        if not season or not week or not pred.get("leans"):
            continue
        rush = week_rushing(season, week)
        played = [l for l in pred["leans"] if l["who"] in rush]
        # grade only when most of the week's flagged teams have final boxes
        if len(rush) < 20 or len(played) < max(3, len(pred["leans"]) * 0.7):
            print(f"  {key}: week not complete ({len(played)}/{len(pred['leans'])} "
                  f"flagged teams final) — will retry")
            continue
        results["weeks"][key] = grade_week(pred, rush)
        g = results["weeks"][key]["leans"]
        w = sum(1 for x in g if x["hit"])
        n = sum(1 for x in g if x["hit"] is not None)
        print(f"  {key}: graded {n} leans — {w}W {n - w}L "
              f"(week median {results['weeks'][key]['medYpc']} YPC)")
        new += 1

    allg = [x for wk in results["weeks"].values() for x in wk["leans"]
            if x["hit"] is not None]
    def rec(rows):
        return dict(n=len(rows), w=sum(1 for r in rows if r["hit"]))
    results["summary"] = dict(
        weeks=len(results["weeks"]),
        overall=rec(allg),
        targets=rec([x for x in allg if x["side"] == "TARGET"]),
        fades=rec([x for x in allg if x["side"] == "FADE"]),
        stacked=rec([x for x in allg if x["k"] == "STACKED RUSH"]))
    os.makedirs(os.path.dirname(RESULTS), exist_ok=True)
    json.dump(results, open(RESULTS, "w"), separators=(",", ":"))

    # slim public record: summary + the last 4 graded weeks in full
    recent = []
    for key in sorted(results["weeks"], reverse=True)[:4]:
        wk = results["weeks"][key]
        recent.append(dict(week=key, medYpc=wk["medYpc"],
                           leans=[x for x in wk["leans"] if x["hit"] is not None]))
    json.dump(dict(summary=results["summary"], recent=recent),
              open(RECORD, "w"), separators=(",", ":"))
    print(f"graded {new} new week(s) · record: {results['summary']}")


if __name__ == "__main__":
    main()
