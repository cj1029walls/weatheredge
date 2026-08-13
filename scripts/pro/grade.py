#!/usr/bin/env python3
"""DFSRADAR PRO — nightly results grading.

Grades every archived PRO card (data/pro/predictions/<YYYYMMDD>.json) against
real MLB boxscores: did each HR target actually homer, did each K lean beat
the line. Maintains a cumulative record with a calibration table (our stated
probability vs the actual hit rate, bucketed) — the public receipts that both
sell the product and tune the model.

Outputs:
  data/pro/results.json   (committed — full graded history)
  site/pro/record.json    (deployed — summary + recent nights for the page)

Runs in the daily workflow before the PRO build. No third-party dependencies.
"""
import functools, json, os, sys, time, unicodedata, urllib.request
from datetime import datetime, timedelta, timezone

print = functools.partial(print, flush=True)

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
PRED_DIR = os.path.join(ROOT, "data", "pro", "predictions")
RESULTS = os.path.join(ROOT, "data", "pro", "results.json")
RECORD = os.path.join(ROOT, "site", "pro", "record.json")

ET = timezone(timedelta(hours=-4))
SCHED = "https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={d}"
BOX = "https://statsapi.mlb.com/api/v1/game/{pk}/boxscore"


def get_json(url, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "dfsradar-pro/1.0"})
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read())
        except Exception as e:
            if i == tries - 1:
                raise
            print(f"    retry {i+1}/{tries}: {e}")
            time.sleep(6 * (i + 1))


def norm_name(s):
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower().replace(".", "").replace("jr", "").strip()


def day_stats(dstr):
    """(name -> {hr, k, ab} actuals, gamePk -> total game HRs) for that date."""
    d = f"{dstr[4:6]}/{dstr[6:8]}/{dstr[:4]}"
    sched = get_json(SCHED.format(d=d))
    stats, game_hr = {}, {}
    for day in sched.get("dates", []):
        for g in day.get("games", []):
            if g.get("status", {}).get("abstractGameState") != "Final":
                continue
            try:
                box = get_json(BOX.format(pk=g["gamePk"]))
            except Exception as e:
                print(f"  boxscore {g['gamePk']} unavailable ({e})")
                continue
            tot = 0
            for side in ("home", "away"):
                tot += ((box["teams"][side].get("teamStats") or {})
                        .get("batting") or {}).get("homeRuns") or 0
                for pl in box["teams"][side]["players"].values():
                    nm = norm_name((pl.get("person") or {}).get("fullName", ""))
                    if not nm:
                        continue
                    bat = (pl.get("stats") or {}).get("batting") or {}
                    pit = (pl.get("stats") or {}).get("pitching") or {}
                    e = stats.setdefault(nm, {"hr": 0, "k": 0, "ab": 0})
                    e["hr"] += bat.get("homeRuns") or 0
                    e["ab"] += bat.get("atBats") or 0
                    e["k"] += pit.get("strikeOuts") or 0
            game_hr[g["gamePk"]] = tot
            time.sleep(0.25)
    return stats, game_hr


def grade_day(pred, stats, game_hr):
    """Pure grading of one archived card against actual stats."""
    tg = []
    for t in pred.get("targets", []):
        s = stats.get(norm_name(t["player"]))
        hit = None if s is None or s.get("ab", 0) == 0 else (s.get("hr", 0) >= 1)
        tg.append(dict(player=t["player"], team=t.get("team"), game=t.get("game"),
                       prob=t.get("prob"), price=t.get("price"),
                       value=bool(t.get("value")), hit=hit))
    kk = []
    for k in pred.get("kprops", []):
        if k.get("line") is None:
            continue
        s = stats.get(norm_name(k["pitcher"]))
        act = s.get("k") if s else None
        res = None if act is None else ("over" if act > k["line"] else "under")
        win = None
        if res is not None and k.get("lean"):
            win = (k["lean"] == "OVER") == (res == "over")
        kk.append(dict(pitcher=k["pitcher"], game=k.get("game"), proj=k.get("proj"),
                       line=k["line"], lean=k.get("lean"), actual=act, res=res, win=win))
    gg = []
    for g in pred.get("games", []):
        act = game_hr.get(g.get("pk"))
        if act is None or not g.get("expHr"):
            continue
        gg.append(dict(pk=g.get("pk"), m=g.get("m"), exp=g["expHr"], act=act,
                       delta=round(act - g["expHr"], 2),
                       ump=g.get("ump"), umpVslg=g.get("umpVslg")))
    return dict(targets=tg, k=kk, games=gg)


ADV_DIR = os.path.join(ROOT, "data", "pro", "adv_predictions")

def grade_adv(dstr, stats, game_hr):
    """Grade the Advanced Model's archived pre-game snapshot for one night.
    Returns None when no clean (pre-game) snapshot exists."""
    path = os.path.join(ADV_DIR, f"{dstr}.json")
    if not os.path.exists(path):
        return None
    try:
        arc = json.load(open(path))
    except Exception:
        return None
    if arc.get("postGame"):
        return None                       # contaminated snapshot — excluded
    gg = []
    for g in arc.get("slate", []):
        act = game_hr.get(g.get("gamePk"))
        proj = g.get("projectedHr")
        if act is None or proj is None:
            continue
        gg.append(dict(pk=g["gamePk"], m=f"{g.get('away')} @ {g.get('home')}",
                       exp=proj, act=act, delta=round(act - proj, 2)))
    top = ((arc.get("stars") or {}).get("topBatter") or {})
    top_hit = None
    if top.get("name"):
        s = stats.get(norm_name(top["name"]))
        if s is not None and s.get("ab", 0) > 0:
            top_hit = s.get("hr", 0) >= 1
    return dict(games=gg,
                top=(dict(player=top.get("name"), score=top.get("combinedHrScore"),
                          hit=top_hit) if top.get("name") else None))


def summarize(days):
    all_t = [t for d in days.values() for t in d["targets"] if t["hit"] is not None]
    cal = []
    for lo, hi in ((0, 15), (15, 20), (20, 25), (25, 101)):
        rows = [t for t in all_t if lo <= (t["prob"] or 0) < hi]
        if rows:
            cal.append(dict(range=f"{lo}–{hi if hi<101 else '+'}", n=len(rows),
                            exp=round(sum(r["prob"] for r in rows) / len(rows), 1),
                            act=round(100 * sum(1 for r in rows if r["hit"]) / len(rows), 1)))
    vals = [t for t in all_t if t["value"]]
    v_w = sum(1 for t in vals if t["hit"])
    units = round(sum((t["price"] / 100 if t["hit"] else -1)
                      for t in vals if t.get("price")), 2)
    top1 = []
    for dstr in sorted(days):
        graded = [t for t in days[dstr]["targets"] if t["hit"] is not None]
        if graded:
            top1.append(graded[0]["hit"])
    kleans = [k for d in days.values() for k in d["k"] if k.get("win") is not None]
    k_w = sum(1 for k in kleans if k["win"])
    # game-level projection accuracy (his "Within 1 / Within 2" module, ours)
    gg = [g for d in days.values() for g in d.get("games", [])]
    game_proj = None
    if gg:
        errs = [abs(g["delta"]) for g in gg]
        game_proj = dict(n=len(gg),
                         avgErr=round(sum(errs) / len(errs), 2),
                         w1=round(100 * sum(1 for e in errs if e <= 1) / len(errs)),
                         w2=round(100 * sum(1 for e in errs if e <= 2) / len(errs)))
    # umpire reliability: in non-neutral ump games (career |vslg| >= 5%), did
    # the game land on the same side of league average as the ump's tendency?
    LG_HRPG = 2.4
    sig = [g for g in gg if g.get("umpVslg") is not None and abs(g["umpVslg"]) >= 5
           and g["act"] != LG_HRPG]
    ump_signal = None
    if sig:
        w = sum(1 for g in sig if (g["act"] > LG_HRPG) == (g["umpVslg"] > 0))
        ump_signal = dict(n=len(sig), w=w, pct=round(100 * w / len(sig)))
    # ---- Model Lab head-to-head: our expHr vs the Advanced Model's
    # projectedHr, same nights, same games (matched by gamePk), same actuals.
    lab = None
    pairs, night_w = [], dict(ours=0, adv=0, push=0)
    adv_top = []
    for dstr in sorted(days):
        d = days[dstr]
        adv = d.get("adv")
        if not adv or not adv.get("games"):
            continue
        ours_by_pk = {g["pk"]: g for g in d.get("games", []) if g.get("pk")}
        night_pairs = []
        for ag in adv["games"]:
            og = ours_by_pk.get(ag["pk"])
            if og:
                night_pairs.append((abs(og["delta"]), abs(ag["delta"])))
        pairs.extend(night_pairs)
        if night_pairs:
            o_err = sum(p[0] for p in night_pairs) / len(night_pairs)
            a_err = sum(p[1] for p in night_pairs) / len(night_pairs)
            if abs(o_err - a_err) < 1e-9:
                night_w["push"] += 1
            elif o_err < a_err:
                night_w["ours"] += 1
            else:
                night_w["adv"] += 1
        if adv.get("top") and adv["top"].get("hit") is not None:
            adv_top.append(adv["top"]["hit"])
    if pairs:
        n = len(pairs)
        lab = dict(
            n=n, nights=sum(night_w.values()), nightW=night_w,
            ours=dict(avgErr=round(sum(p[0] for p in pairs) / n, 2),
                      w1=round(100 * sum(1 for p in pairs if p[0] <= 1) / n),
                      w2=round(100 * sum(1 for p in pairs if p[0] <= 2) / n)),
            adv=dict(avgErr=round(sum(p[1] for p in pairs) / n, 2),
                     w1=round(100 * sum(1 for p in pairs if p[1] <= 1) / n),
                     w2=round(100 * sum(1 for p in pairs if p[1] <= 2) / n)),
            advTop=dict(n=len(adv_top), w=sum(1 for h in adv_top if h)))
    return dict(nights=len(days), graded=len(all_t), cal=cal,
                value=dict(n=len(vals), w=v_w, units=units),
                top1=dict(n=len(top1), w=sum(1 for h in top1 if h)),
                kleans=dict(n=len(kleans), w=k_w),
                gameProj=game_proj, umpSignal=ump_signal, lab=lab)


def main():
    if not os.path.isdir(PRED_DIR):
        print("no predictions archived yet — nothing to grade")
        return
    results = json.load(open(RESULTS)) if os.path.exists(RESULTS) else {"days": {}}
    today = datetime.now(ET).strftime("%Y%m%d")
    new = 0
    for f in sorted(os.listdir(PRED_DIR)):
        if not f.endswith(".json"):
            continue
        dstr = f[:-5]
        if dstr >= today or dstr in results["days"]:
            continue
        pred = json.load(open(os.path.join(PRED_DIR, f)))
        stats, game_hr = day_stats(dstr)
        if len(stats) < 50:
            print(f"  {dstr}: boxscores not ready ({len(stats)} players) — will retry")
            continue
        results["days"][dstr] = grade_day(pred, stats, game_hr)
        adv = grade_adv(dstr, stats, game_hr)
        if adv:
            results["days"][dstr]["adv"] = adv
            print(f"  {dstr}: advanced model graded on {len(adv['games'])} games")
        g = results["days"][dstr]
        hits = sum(1 for t in g["targets"] if t["hit"])
        print(f"  {dstr}: graded {len(g['targets'])} targets ({hits} homered), "
              f"{len(g['k'])} K lines")
        new += 1
    results["summary"] = summarize(results["days"])
    results["updated"] = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    os.makedirs(os.path.dirname(RESULTS), exist_ok=True)
    with open(RESULTS, "w") as fo:
        json.dump(results, fo, separators=(",", ":"))
    # slim public record for the page: summary + last 10 nights
    recent = []
    for dstr in sorted(results["days"], reverse=True)[:10]:
        d = results["days"][dstr]
        graded = [t for t in d["targets"] if t["hit"] is not None]
        recent.append(dict(
            d=dstr, n=len(graded), hits=sum(1 for t in graded if t["hit"]),
            top=(dict(player=graded[0]["player"], prob=graded[0]["prob"],
                      hit=graded[0]["hit"]) if graded else None),
            valueHits=[dict(player=t["player"], price=t.get("price"), hit=t["hit"])
                       for t in d["targets"] if t["value"]],
            kW=sum(1 for k in d["k"] if k.get("win")),
            kN=sum(1 for k in d["k"] if k.get("win") is not None)))
    with open(RECORD, "w") as fo:
        json.dump(dict(summary=results["summary"], updated=results["updated"],
                       recent=recent), fo, separators=(",", ":"))
    print(f"Graded {new} new night(s). Record: {results['summary']}")


if __name__ == "__main__":
    main()
