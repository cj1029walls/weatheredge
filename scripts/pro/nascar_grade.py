#!/usr/bin/env python3
"""DFSRADAR PRO — NASCAR track-target grading.

Grades every archived race board (data/pro/nascar_predictions/<date>-<track>.json)
against ESPN's official finishing order once the race completes.

The bars are stated, fixed, and the same ones the page advertises:
  * a TRACK TARGET hits on a top-10 finish
  * a DOMINATOR hits on a top-5 finish — it is the stronger claim, so it
    carries the stronger bar
A driver who doesn't appear in the finishing order (withdrew, failed to
qualify) is left ungraded rather than counted as a loss.

Outputs:
  data/pro/nascar_results.json   (committed — full graded history)
  site/pro/nascar_record.json    (deployed — summary + recent races)

Runs in the NASCAR weekly workflow before the board build. No third-party deps.
"""
import functools, json, os, re, unicodedata, urllib.request
from datetime import date

print = functools.partial(print, flush=True)

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
ARCH = os.path.join(ROOT, "data", "pro", "nascar_predictions")
RESULTS = os.path.join(ROOT, "data", "pro", "nascar_results.json")
RECORD = os.path.join(ROOT, "site", "pro", "nascar_record.json")

SB_URL = ("https://site.web.api.espn.com/apis/site/v2/sports/racing/"
          "nascar-premier/scoreboard?dates={y}")

BAR = {"TRACK TARGET": 10, "DOMINATOR": 5}
DEFAULT_BAR = 10


def get_json(url, tries=4, timeout=90):
    last = None
    for _ in range(tries):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "dfsradar-grade/1.0",
                              "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except Exception as e:
            last = e
    raise last


def norm_driver(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z ]", "", s.lower()).strip()


def season_results(year, _cache={}):
    """{race date -> {name, n, order{driver: pos}}} for one completed season."""
    if year in _cache:
        return _cache[year]
    out = {}
    try:
        sb = get_json(SB_URL.format(y=year))
    except Exception as e:
        print(f"  season {year}: finishing order unavailable ({e})")
        _cache[year] = out
        return out
    for ev in sb.get("events") or []:
        comps = ev.get("competitions") or []
        if not comps:
            continue
        if ((ev.get("status") or {}).get("type") or {}).get("completed") is not True:
            continue
        rows = comps[0].get("competitors") or []
        if len(rows) < 20:
            continue
        d = (ev.get("date") or "")[:10]
        if not d:
            continue
        order = {}
        for i, c in enumerate(rows):
            ath = (c.get("athlete") or {}).get("displayName")
            if not ath:
                continue
            pos = c.get("order") or (i + 1)
            try:
                order[norm_driver(ath)] = int(pos)
            except (TypeError, ValueError):
                continue
        if order:
            out[d] = dict(name=ev.get("name") or "", n=len(rows), order=order)
    _cache[year] = out
    print(f"  season {year}: {len(out)} completed races on the results feed")
    return out


def main():
    if not os.path.isdir(ARCH):
        print("no archived NASCAR boards yet — nothing to grade")
        return
    results = json.load(open(RESULTS)) if os.path.exists(RESULTS) else {"races": {}}
    results.setdefault("races", {})
    today = date.today().isoformat()
    new = 0

    for fn in sorted(os.listdir(ARCH)):
        if not fn.endswith(".json"):
            continue
        akey = fn[:-5]
        if akey in results["races"]:
            continue
        pred = json.load(open(os.path.join(ARCH, fn)))
        d, leans = pred.get("date"), pred.get("leans") or []
        if not d or not leans:
            continue
        if d >= today:
            print(f"  {akey}: race not run yet")
            continue

        season = season_results(int(d[:4]))
        race = season.get(d)
        if not race:
            print(f"  {akey}: not final on the results feed yet — will retry")
            continue

        graded = []
        for ln in leans:
            k = ln.get("k")
            bar = BAR.get(k, DEFAULT_BAR)
            side = ln.get("side")
            pos = race["order"].get(norm_driver(ln.get("who")))
            # a FADE claims the driver runs poorly — it hits when he finishes
            # OUTSIDE the bar, the mirror of a TARGET
            hit = None if pos is None else (pos > bar if side == "FADE"
                                            else pos <= bar)
            graded.append(dict(k=k, side=side, who=ln.get("who"),
                               why=ln.get("why"), pos=pos, bar=bar,
                               field=race["n"], hit=hit))
        done = [g for g in graded if g["hit"] is not None]
        results["races"][akey] = dict(race=race["name"] or pred.get("race"),
                                      date=d, field=race["n"], leans=graded)
        print(f"  {akey}: graded {len(done)}/{len(graded)} leans — "
              f"{sum(1 for g in done if g['hit'])}W {sum(1 for g in done if not g['hit'])}L")
        new += 1

    allg = [x for r in results["races"].values() for x in r["leans"]
            if x["hit"] is not None]

    def rec(rows):
        return dict(n=len(rows), w=sum(1 for r in rows if r["hit"]))

    finishes = [x["pos"] for x in allg if x["pos"]]
    results["summary"] = dict(
        races=len(results["races"]),
        bar="top-10 finish (top-5 for DOMINATOR)",
        overall=rec(allg),
        trackTarget=rec([x for x in allg if x["k"] == "TRACK TARGET"]),
        dominator=rec([x for x in allg if x["k"] == "DOMINATOR"]),
        avgFinish=round(sum(finishes) / len(finishes), 1) if finishes else None,
        wins=sum(1 for x in allg if x["pos"] == 1),
        top5=sum(1 for x in allg if x["pos"] and x["pos"] <= 5))
    os.makedirs(os.path.dirname(RESULTS), exist_ok=True)
    json.dump(results, open(RESULTS, "w"), separators=(",", ":"))

    recent = []
    for k in sorted(results["races"],
                    key=lambda k: results["races"][k].get("date") or "",
                    reverse=True)[:4]:
        r = results["races"][k]
        recent.append(dict(race=r["race"], date=r.get("date"), field=r.get("field"),
                           leans=[x for x in r["leans"] if x["hit"] is not None]))
    os.makedirs(os.path.dirname(RECORD), exist_ok=True)
    json.dump(dict(summary=results["summary"], recent=recent),
              open(RECORD, "w"), separators=(",", ":"))
    print(f"graded {new} new race(s) · record: {results['summary']}")


if __name__ == "__main__":
    main()
