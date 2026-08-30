#!/usr/bin/env python3
"""DFSRADAR PRO — NFL weekly grading.

Grades every archived weekly board (data/pro/nfl_predictions/<season>-w<week>.json)
once that week's games are final:

  * priced player-prop leans (QB WIND/COLD pass yds, RB WIND/COLD rush yds,
    WR WIND receptions, KICKER kicking pts) vs actual stat lines from
    nflverse weekly player stats — graded ONLY when a live line was archived
  * REF TOTAL and SPOT over/under leans vs the archived closing total
  * COLD team-total leans vs the spread/total-implied team total

Outputs:
  data/pro/nfl_results.json   (committed — full graded history)
  site/pro/nfl_record.json    (deployed — summary + recent weeks for the page)

Runs in the NFL weekly workflow before the board build. No third-party deps.
"""
import csv, functools, gzip, io, json, os, re, unicodedata, urllib.request

print = functools.partial(print, flush=True)

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
ARCH = os.path.join(ROOT, "data", "pro", "nfl_predictions")
RESULTS = os.path.join(ROOT, "data", "pro", "nfl_results.json")
RECORD = os.path.join(ROOT, "site", "pro", "nfl_record.json")

STATS_URL = ("https://github.com/nflverse/nflverse-data/releases/download/"
             "player_stats/player_stats_{season}.csv.gz")
KICK_URL = ("https://github.com/nflverse/nflverse-data/releases/download/"
            "player_stats/player_stats_kicking_{season}.csv.gz")
GAMES_URL = "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv"


def fetch(url, timeout=180):
    req = urllib.request.Request(url, headers={"User-Agent": "dfsradar-grade/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def read_csv_gz(raw):
    f = io.TextIOWrapper(gzip.GzipFile(fileobj=io.BytesIO(raw)),
                         encoding="utf-8", errors="replace")
    return list(csv.DictReader(f))


def norm_name(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z. ]", "", s).strip()
    parts = re.split(r"[. ]+", s)
    return parts[-1].lower() if parts else ""


def week_stats(season, week):
    """(player last name -> {passYds, rushYds, rec, kickPts}) for one week."""
    out = {}
    try:
        for r in read_csv_gz(fetch(STATS_URL.format(season=season))):
            if str(r.get("week")) != str(week):
                continue
            nm = norm_name(r.get("player_display_name") or r.get("player_name"))
            if not nm:
                continue
            e = out.setdefault(nm, {})
            for k, col in (("passYds", "passing_yards"), ("rushYds", "rushing_yards"),
                           ("rec", "receptions")):
                try:
                    e[k] = e.get(k, 0) + float(r.get(col) or 0)
                except (TypeError, ValueError):
                    pass
    except Exception as e:
        print(f"  player stats unavailable ({e})")
        return None
    try:
        for r in read_csv_gz(fetch(KICK_URL.format(season=season))):
            if str(r.get("week")) != str(week):
                continue
            nm = norm_name(r.get("player_display_name") or r.get("player_name"))
            if not nm:
                continue
            try:
                fgm = float(r.get("fg_made") or 0)
                pat = float(r.get("pat_made") or 0)
                out.setdefault(nm, {})["kickPts"] = fgm * 3 + pat
            except (TypeError, ValueError):
                pass
    except Exception as e:
        print(f"  kicking stats unavailable ({e}) — kicker leans stay ungraded")
    return out


def week_scores(season, week):
    """{'AWY@HOM': (away_pts, home_pts)} finals for the week."""
    out = {}
    try:
        rows = csv.DictReader(io.TextIOWrapper(io.BytesIO(fetch(GAMES_URL)),
                                               encoding="utf-8"))
        for r in rows:
            if str(r.get("season")) != str(season) or str(r.get("week")) != str(week):
                continue
            a, h = r.get("away_score"), r.get("home_score")
            if (a or "").strip() == "" or (h or "").strip() == "":
                continue
            out[f"{r['away_team']}@{r['home_team']}"] = (float(a), float(h))
    except Exception as e:
        print(f"  scores unavailable ({e})")
    return out


PLAYER_PROPS = {"pass yds": "passYds", "rush yds": "rushYds",
                "receptions": "rec", "kicking pts": "kickPts"}


def implied_team_total(g, team):
    """Closing-total/spread implied points for one team, from the archive row."""
    if g.get("total") is None or not g.get("spread"):
        return None
    m = re.match(r"([A-Z]{2,3}) -([\d.]+)", g["spread"])
    if not m:
        return g["total"] / 2
    fav, pts = m.group(1), float(m.group(2))
    half = g["total"] / 2
    return half + pts / 2 if team == fav else half - pts / 2


def grade_week(pred, stats, scores):
    graded = []
    gmap = {f"{g['away']}@{g['home']}": g for g in pred.get("games", [])}
    for ln in pred.get("leans", []):
        entry = dict(k=ln["k"], side=ln["side"], who=ln.get("who"),
                     game=ln["game"], prop=ln.get("prop"),
                     line=ln.get("line"), price=ln.get("price"), hit=None)
        stat_key = PLAYER_PROPS.get(ln.get("prop") or "")
        fin = scores.get(ln["game"])
        if stat_key and ln.get("line") is not None:
            nm = norm_name((ln.get("who") or "").split("(")[0])
            act = (stats or {}).get(nm, {}).get(stat_key)
            if act is not None and ln["side"] in ("OVER", "UNDER"):
                entry["act"] = round(act, 1)
                entry["hit"] = (act > ln["line"]) if ln["side"] == "OVER" \
                    else (act < ln["line"])
        elif ln["k"] in ("REF TOTAL", "SPOT") and ln["side"] in ("OVER", "UNDER") and fin:
            g = gmap.get(ln["game"])
            if g and g.get("total") is not None:
                tot = fin[0] + fin[1]
                entry["act"] = tot
                entry["line"] = g["total"]
                entry["hit"] = (tot > g["total"]) if ln["side"] == "OVER" \
                    else (tot < g["total"])
        elif ln["k"] == "COLD" and ln.get("prop") == "team total" and fin:
            g = gmap.get(ln["game"])
            itt = implied_team_total(g, ln.get("who")) if g else None
            if itt is not None:
                a, h = ln["game"].split("@")
                pts = fin[0] if ln.get("who") == a else fin[1]
                entry["act"] = pts
                entry["line"] = round(itt, 1)
                entry["hit"] = pts < itt
        graded.append(entry)
    return graded


def main():
    if not os.path.isdir(ARCH):
        print("no archived boards yet — nothing to grade")
        return
    results = json.load(open(RESULTS)) if os.path.exists(RESULTS) else {"weeks": {}}
    new = 0
    for f in sorted(os.listdir(ARCH)):
        if not f.endswith(".json"):
            continue
        key = f[:-5]
        if key in results["weeks"]:
            continue
        pred = json.load(open(os.path.join(ARCH, f)))
        season, week = pred.get("season"), pred.get("week")
        if not season or not week or not pred.get("leans"):
            continue
        scores = week_scores(season, week)
        need = {f"{g['away']}@{g['home']}" for g in pred.get("games", [])}
        if not need or len(scores.keys() & need) < len(need) * 0.9:
            print(f"  {key}: week not final ({len(scores.keys() & need)}/{len(need)} "
                  f"scores) — will retry")
            continue
        stats = week_stats(season, week)
        graded = grade_week(pred, stats, scores)
        done = [x for x in graded if x["hit"] is not None]
        results["weeks"][key] = dict(leans=graded)
        print(f"  {key}: graded {len(done)}/{len(graded)} leans — "
              f"{sum(1 for x in done if x['hit'])}W {sum(1 for x in done if not x['hit'])}L")
        new += 1

    allg = [x for wk in results["weeks"].values() for x in wk["leans"]
            if x["hit"] is not None]
    def rec(rows):
        return dict(n=len(rows), w=sum(1 for r in rows if r["hit"]))
    kinds = sorted({x["k"] for x in allg})
    results["summary"] = dict(
        weeks=len(results["weeks"]), overall=rec(allg),
        props=rec([x for x in allg if x.get("prop") in PLAYER_PROPS]),
        byKind={k: rec([x for x in allg if x["k"] == k]) for k in kinds})
    os.makedirs(os.path.dirname(RESULTS), exist_ok=True)
    json.dump(results, open(RESULTS, "w"), separators=(",", ":"))

    recent = []
    for key in sorted(results["weeks"], reverse=True)[:4]:
        recent.append(dict(week=key,
                           leans=[x for x in results["weeks"][key]["leans"]
                                  if x["hit"] is not None]))
    json.dump(dict(summary=results["summary"], recent=recent),
              open(RECORD, "w"), separators=(",", ":"))
    print(f"graded {new} new week(s) · record: {results['summary']}")


if __name__ == "__main__":
    main()
