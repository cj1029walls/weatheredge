#!/usr/bin/env python3
"""DFSRADAR PRO — Advanced Model (beta) card -> site/pro/adv.json

Pulls the partner model's computed output VERBATIM from its live API
(umpire-analytics.replit.app). Nothing is recomputed or adjusted here — the
whole point of the Model Lab is an exact side-by-side, so this script is a
courier, not a model: fetch, stamp, archive.

Outputs:
  site/pro/adv.json                          (deployed — tonight's card)
  data/pro/adv_predictions/<YYYYMMDD>.json   (committed — for grading)

Archive integrity rule: a date's archive is overwritten on refresh ONLY while
no game on that slate has gone Final. Once the first game finishes, the
snapshot is locked — projections recorded after results start arriving would
contaminate the comparison.

Failure mode: if the API is unreachable, the previous site/pro/adv.json is
left in place and the build continues (the Lab tab shows its build time).

No third-party dependencies.
"""
import functools, json, os, time, urllib.request
from datetime import datetime, timedelta, timezone

print = functools.partial(print, flush=True)

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
OUT = os.path.join(ROOT, "site", "pro", "adv.json")
ARCH = os.path.join(ROOT, "data", "pro", "adv_predictions")

BASE = os.environ.get("ADV_MODEL_BASE", "https://umpire-analytics.replit.app")
ET = timezone(timedelta(hours=-4))


def get_json(path, tries=3):
    url = BASE + path
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                "Accept": "application/json",
            })
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read())
        except Exception as e:
            if i == tries - 1:
                raise
            print(f"    retry {i+1}/{tries} {path}: {e}")
            time.sleep(6 * (i + 1))


def main():
    try:
        slate = get_json("/api/slate")
        stars = get_json("/api/tonight/stars")
    except Exception as e:
        print(f"advanced model API unreachable ({e}) — keeping last card")
        return
    overview = {}
    try:
        overview = get_json("/api/overview", tries=1)
    except Exception:
        pass

    if not isinstance(slate, list):
        print("unexpected slate shape — keeping last card")
        return

    now = datetime.now(ET)
    out = dict(
        fetched=now.strftime("%Y-%m-%d %H:%M ET"),
        source=BASE,
        generatedAt=(stars or {}).get("generatedAt"),
        dataset=dict(games=overview.get("totalGames"),
                     hrPerGame=overview.get("hrPerGame"),
                     lastDate=overview.get("lastDate")),
        slate=slate,          # verbatim
        stars=stars)          # verbatim
    json.dump(out, open(OUT, "w"), separators=(",", ":"))
    print(f"wrote {OUT}: {len(slate)} games · top batter "
          f"{((stars or {}).get('topBatter') or {}).get('name')}")

    # ---- archive per slate date, locked once any game is Final
    os.makedirs(ARCH, exist_ok=True)
    by_date = {}
    for g in slate:
        d = (g.get("date") or "").replace("-", "")
        if len(d) == 8:
            by_date.setdefault(d, []).append(g)
    for d, rows in by_date.items():
        path = os.path.join(ARCH, f"{d}.json")
        locked_now = any((g.get("status") or "") == "Final" for g in rows)
        prior = None
        if os.path.exists(path):
            try:
                prior = json.load(open(path))
            except Exception:
                prior = None
        if prior and prior.get("locked"):
            print(f"  archive {d}: locked — kept pre-game snapshot")
            continue
        if prior and locked_now:
            # results started arriving — freeze the existing PRE-GAME snapshot
            prior["locked"] = True
            json.dump(prior, open(path, "w"), separators=(",", ":"))
            print(f"  archive {d}: pre-game snapshot frozen")
            continue
        # postGame=True marks a first-ever snapshot taken AFTER results
        # started — the grader excludes those nights from the head-to-head.
        json.dump(dict(archived=out["fetched"], generatedAt=out["generatedAt"],
                       locked=locked_now, postGame=locked_now,
                       slate=rows,
                       stars=(stars if not locked_now else None)),
                  open(path, "w"), separators=(",", ":"))
        print(f"  archive {d}: {len(rows)} games{' (post-game — excluded from grading)' if locked_now else ''}")


if __name__ == "__main__":
    main()
