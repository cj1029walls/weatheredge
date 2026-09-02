#!/usr/bin/env python3
"""DFSRADAR PRO — PGA course-horse grading.

Grades every archived event board (data/pro/pga_predictions/<year>-<key>.json)
against ESPN's final leaderboard once the event completes.

The bar is stated, fixed, and the same one the page advertises:
  * a COURSE HORSE TARGET hits on a top-20 finish
  * a missed cut is a loss (ESPN orders cut players behind the field)
Nothing is graded until ESPN reports the event completed, and a player who
never teed off (WD before round 1, no leaderboard row) is left ungraded
rather than counted as a loss.

Outputs:
  data/pro/pga_results.json     (committed — full graded history)
  site/pro/pga_record.json      (deployed — summary + recent events)

Runs in the PGA weekly workflow before the board build. No third-party deps.
"""
import functools, json, os, re, unicodedata, urllib.request
from datetime import date

print = functools.partial(print, flush=True)

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
ARCH = os.path.join(ROOT, "data", "pro", "pga_predictions")
RESULTS = os.path.join(ROOT, "data", "pro", "pga_results.json")
RECORD = os.path.join(ROOT, "site", "pro", "pga_record.json")

SB_URL = "https://site.web.api.espn.com/apis/site/v2/sports/golf/pga/scoreboard?dates={y}"

TOP_N = 20          # a COURSE HORSE hits on a top-20 finish


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


def norm_player(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z ]", "", s.lower()).strip()


def norm_event(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", s.lower())


def season_results(year, _cache={}):
    """{normalized event name: {player -> finishing position}} for one season.

    Only events ESPN reports completed are returned, so an in-progress
    tournament is never graded."""
    if year in _cache:
        return _cache[year]
    out = {}
    try:
        sb = get_json(SB_URL.format(y=year))
    except Exception as e:
        print(f"  season {year}: leaderboard unavailable ({e})")
        _cache[year] = out
        return out
    for ev in sb.get("events") or []:
        name = ev.get("name") or ""
        comps = ev.get("competitions") or []
        if not name or not comps:
            continue
        if ((ev.get("status") or {}).get("type") or {}).get("completed") is not True:
            continue
        rows = comps[0].get("competitors") or []
        if len(rows) < 20:
            continue
        board = {}
        for i, c in enumerate(rows):
            ath = (c.get("athlete") or {}).get("displayName")
            if not ath:
                continue
            pos = c.get("order") or (i + 1)
            try:
                board[norm_player(ath)] = int(pos)
            except (TypeError, ValueError):
                continue
        if board:
            out[norm_event(name)] = dict(name=name, n=len(rows), board=board,
                                         date=(ev.get("date") or "")[:10])
    _cache[year] = out
    print(f"  season {year}: {len(out)} completed events on the leaderboard feed")
    return out


def find_event(results, archived_name, key):
    """Match an archived board to its ESPN event by name, then by key."""
    want = norm_event(archived_name)
    if want in results:
        return results[want]
    for k, ev in results.items():
        if want and (want in k or k in want):
            return ev
    kk = norm_event(key)
    for k, ev in results.items():
        if kk and kk in k:
            return ev
    return None


def main():
    if not os.path.isdir(ARCH):
        print("no archived PGA boards yet — nothing to grade")
        return
    results = json.load(open(RESULTS)) if os.path.exists(RESULTS) else {"events": {}}
    results.setdefault("events", {})
    today = date.today().isoformat()
    new = 0

    for fn in sorted(os.listdir(ARCH)):
        if not fn.endswith(".json"):
            continue
        akey = fn[:-5]
        if akey in results["events"]:
            continue
        pred = json.load(open(os.path.join(ARCH, fn)))
        year, leans = pred.get("year"), pred.get("leans") or []
        if not year or not leans:
            continue

        ev = find_event(season_results(int(year)), pred.get("event") or "",
                        pred.get("key") or "")
        if not ev:
            print(f"  {akey}: not final on the leaderboard feed yet — will retry")
            continue
        if ev.get("date") and ev["date"] >= today:
            print(f"  {akey}: finishes today — holding until tomorrow's run")
            continue

        graded = []
        for ln in leans:
            side = ln.get("side")
            pos = ev["board"].get(norm_player(ln.get("who")))
            # a FADE hits when the player finishes outside the bar
            hit = None if pos is None else (pos > TOP_N if side == "FADE"
                                            else pos <= TOP_N)
            graded.append(dict(k=ln.get("k"), side=side,
                               who=ln.get("who"), why=ln.get("why"),
                               pos=pos, field=ev["n"], hit=hit))
        done = [g for g in graded if g["hit"] is not None]
        results["events"][akey] = dict(event=ev["name"], date=ev.get("date"),
                                       field=ev["n"], leans=graded)
        print(f"  {akey}: graded {len(done)}/{len(graded)} leans — "
              f"{sum(1 for g in done if g['hit'])}W {sum(1 for g in done if not g['hit'])}L")
        new += 1

    allg = [x for e in results["events"].values() for x in e["leans"]
            if x["hit"] is not None]

    def rec(rows):
        return dict(n=len(rows), w=sum(1 for r in rows if r["hit"]))

    wins = [x["pos"] for x in allg if x["pos"]]
    results["summary"] = dict(
        events=len(results["events"]), bar=f"top-{TOP_N} finish",
        overall=rec(allg),
        courseHorse=rec([x for x in allg if x["k"] == "COURSE HORSE"]),
        avgFinish=round(sum(wins) / len(wins), 1) if wins else None,
        wins=sum(1 for x in allg if x["pos"] == 1),
        top5=sum(1 for x in allg if x["pos"] and x["pos"] <= 5))
    os.makedirs(os.path.dirname(RESULTS), exist_ok=True)
    json.dump(results, open(RESULTS, "w"), separators=(",", ":"))

    recent = []
    for k in sorted(results["events"],
                    key=lambda k: results["events"][k].get("date") or "",
                    reverse=True)[:4]:
        e = results["events"][k]
        recent.append(dict(event=e["event"], date=e.get("date"), field=e.get("field"),
                           leans=[x for x in e["leans"] if x["hit"] is not None]))
    os.makedirs(os.path.dirname(RECORD), exist_ok=True)
    json.dump(dict(summary=results["summary"], recent=recent),
              open(RECORD, "w"), separators=(",", ":"))
    print(f"graded {new} new event(s) · record: {results['summary']}")


if __name__ == "__main__":
    main()
