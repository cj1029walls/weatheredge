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
from datetime import date, timedelta

print = functools.partial(print, flush=True)

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
ARCH = os.path.join(ROOT, "data", "pro", "nfl_predictions")
RESULTS = os.path.join(ROOT, "data", "pro", "nfl_results.json")
RECORD = os.path.join(ROOT, "site", "pro", "nfl_record.json")

# nflverse moved weekly player stats to the `stats_player` release in 2025 (one
# file per season, kicking columns included). The old `player_stats` release
# stops at 2024, so for 2025+ it 404s and no player-prop lean ever graded.
STATS_URLS = (
    "https://github.com/nflverse/nflverse-data/releases/download/"
    "stats_player/stats_player_week_{season}.csv.gz",
    "https://github.com/nflverse/nflverse-data/releases/download/"
    "player_stats/player_stats_{season}.csv.gz",          # 2024 and earlier
)
KICK_URL = ("https://github.com/nflverse/nflverse-data/releases/download/"
            "player_stats/player_stats_kicking_{season}.csv.gz")   # legacy only
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
    # suffixes dropped: "Marvin Harrison Jr." used to key as "" (row discarded)
    parts = [p for p in re.split(r"[. ]+", s)
             if p and p.lower() not in ("jr", "sr", "ii", "iii", "iv")]
    return parts[-1].lower() if parts else ""


def row_team(r):
    for col in ("recent_team", "team", "team_abbr", "posteam"):
        v = (r.get(col) or "").strip().upper()
        if v:
            return v
    return ""


def pkey(team, last):
    return f"{(team or '').upper()}|{last}"


def week_stats(season, week):
    """((team|last name) -> {passYds, rushYds, rec, kickPts}) for one week.

    Keyed by TEAM AND surname, never surname alone: a league has several
    Smiths, and pooling them grades a receiver's 3 catches against every
    Smith's combined total. `_last` carries a surname->keys index so a lean
    whose team abbreviation doesn't match the feed can still resolve, but
    only when the surname is unique that week."""
    out, by_last = {}, {}

    def bucket(team, last):
        k = pkey(team, last)
        by_last.setdefault(last, set()).add(k)
        return out.setdefault(k, {})

    rows, errs = None, []
    for url in STATS_URLS:
        try:
            rows = read_csv_gz(fetch(url.format(season=season)))
            break
        except Exception as e:
            errs.append(f"{url.format(season=season).rsplit('/', 2)[-2]}: {e}")
    if rows is None:
        print(f"  player stats unavailable ({'; '.join(errs)})")
        return None
    # the stats_player file carries kicking too; the legacy one needs KICK_URL
    has_kick = bool(rows) and "fg_made" in rows[0] and "pat_made" in rows[0]

    def num(r, col):
        try:
            return float(r.get(col) or 0)
        except (TypeError, ValueError):
            return 0.0

    for r in rows:
        if str(r.get("week")) != str(week):
            continue
        nm = norm_name(r.get("player_display_name") or r.get("player_name"))
        if not nm:
            continue
        e = bucket(row_team(r), nm)
        for k, col in (("passYds", "passing_yards"), ("rushYds", "rushing_yards"),
                       ("rec", "receptions")):
            e[k] = e.get(k, 0) + num(r, col)
        # a kicker who went 0-for-0 still scored 0 kicking points
        if has_kick and ((r.get("position") or "").upper() == "K"
                         or num(r, "fg_att") or num(r, "pat_att")):
            e["kickPts"] = e.get("kickPts", 0) + num(r, "fg_made") * 3 + num(r, "pat_made")
    if has_kick:
        out["_last"] = {k: sorted(v) for k, v in by_last.items()}
        return out
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
                e = bucket(row_team(r), nm)
                e["kickPts"] = e.get("kickPts", 0) + fgm * 3 + pat
            except (TypeError, ValueError):
                pass
    except Exception as e:
        print(f"  kicking stats unavailable ({e}) — kicker leans stay ungraded")
    out["_last"] = {k: sorted(v) for k, v in by_last.items()}
    return out


def player_stat(stats, who, stat_key):
    """Actual stat for the player a lean names, or None if we can't be certain.

    `who` is archived as "Name (TEAM)". We resolve on (team, surname); if that
    misses we accept a surname match only when it is unique in the week."""
    if not stats or not who:
        return None
    m = re.search(r"\(([A-Za-z]{2,4})\)\s*$", who.strip())
    team = m.group(1).upper() if m else ""
    last = norm_name(who.split("(")[0])
    if not last:
        return None
    hit = stats.get(pkey(team, last))
    if hit is None:
        cands = (stats.get("_last") or {}).get(last) or []
        if len(cands) != 1:
            return None                     # ambiguous surname — leave ungraded
        hit = stats.get(cands[0])
    return (hit or {}).get(stat_key)


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
            act = player_stat(stats, ln.get("who"), stat_key)
            if act is not None and ln["side"] in ("OVER", "UNDER"):
                entry["act"] = round(act, 1)
                # an exact landing is a push, not a loss on both sides
                entry["hit"] = None if act == ln["line"] else \
                    (act > ln["line"]) if ln["side"] == "OVER" else (act < ln["line"])
                if entry["hit"] is None:
                    entry["push"] = True
        elif ln["k"] in ("REF TOTAL", "SPOT") and ln["side"] in ("OVER", "UNDER") and fin:
            g = gmap.get(ln["game"])
            if g and g.get("total") is not None:
                tot = fin[0] + fin[1]
                entry["act"] = tot
                entry["line"] = g["total"]
                entry["hit"] = None if tot == g["total"] else \
                    (tot > g["total"]) if ln["side"] == "OVER" else (tot < g["total"])
                if entry["hit"] is None:
                    entry["push"] = True
        elif ln["k"] == "COLD" and ln.get("prop") == "team total" and fin:
            g = gmap.get(ln["game"])
            itt = implied_team_total(g, ln.get("who")) if g else None
            if itt is not None:
                a, h = ln["game"].split("@")
                pts = fin[0] if ln.get("who") == a else fin[1]
                entry["act"] = pts
                entry["line"] = round(itt, 1)
                entry["hit"] = None if pts == itt else (pts < itt)
                if entry["hit"] is None:
                    entry["push"] = True
        graded.append(entry)
    return graded


def stats_cover(stats, leans):
    """True when the weekly player feed has rows for every team a priced
    player-prop lean names. Scores post hours before nflverse's player stats,
    so a final score alone doesn't mean the prop can be graded yet."""
    if not stats:
        return False
    teams = {k.split("|")[0] for k in stats if k != "_last"}
    for ln in leans:
        m = re.search(r"\(([A-Za-z]{2,4})\)\s*$", (ln.get("who") or "").strip())
        if m and m.group(1).upper() not in teams:
            return False
    return True


def week_order(key):
    """Sort archive keys by real week number: '2026-w10' must outrank '2026-w9'."""
    m = re.match(r"(\d+)\D+(\d+)$", key or "")
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


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
        pred = json.load(open(os.path.join(ARCH, f)))
        season, week = pred.get("season"), pred.get("week")
        if not season or not week or not pred.get("leans"):
            continue
        if key in results["weeks"]:
            # Heal weeks sealed before their data was complete (the old 90%
            # rule graded 2026-w1 with MNF unplayed): while a priced lean is
            # still ungraded and the week is under 14 days old, grade it again
            # from the archive — the whole week is rebuilt, never appended.
            open_ = [x for x in results["weeks"][key].get("leans", [])
                     if x.get("hit") is None and x.get("line") is not None]
            last = max((g.get("date") or "" for g in pred.get("games", [])), default="")
            fresh = bool(last) and date.today() <= date.fromisoformat(last) + timedelta(days=14)
            if not open_ or not fresh:
                continue
            print(f"  {key}: {len(open_)} priced lean(s) still ungraded — re-grading")
        scores = week_scores(season, week)
        need = {f"{g['away']}@{g['home']}" for g in pred.get("games", [])}
        # A week is sealed exactly once, so every game that carries a lean must
        # be final first. The old ">= 90% of scores" rule sealed 2026-w1 on
        # Monday morning with DEN@KC (MNF) unplayed, and its four leans stay
        # ungraded for good. A game that never finishes can't block the week
        # forever: four days after the last archived game we grade what we have.
        pending = sorted({ln["game"] for ln in pred["leans"]} - scores.keys())
        last_day = max((g.get("date") or "" for g in pred.get("games", [])), default="")
        overdue = bool(last_day) and date.today() > (
            date.fromisoformat(last_day) + timedelta(days=4))
        if not need or len(scores.keys() & need) < len(need) * 0.9 or (pending and not overdue):
            print(f"  {key}: week not final ({len(scores.keys() & need)}/{len(need)} scores"
                  f"{'; waiting on ' + ', '.join(pending) if pending else ''}) — will retry")
            continue
        stats = week_stats(season, week)
        priced = [ln for ln in pred["leans"] if ln.get("line") is not None
                  and PLAYER_PROPS.get(ln.get("prop") or "")]
        if priced and not stats_cover(stats, priced) and not overdue:
            print(f"  {key}: player stats for week {week} not published yet — will retry")
            continue
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
    for key in sorted(results["weeks"], key=week_order, reverse=True)[:4]:
        recent.append(dict(week=key,
                           leans=[x for x in results["weeks"][key]["leans"]
                                  if x["hit"] is not None]))
    json.dump(dict(summary=results["summary"], recent=recent),
              open(RECORD, "w"), separators=(",", ":"))
    print(f"graded {new} new week(s) · record: {results['summary']}")


if __name__ == "__main__":
    main()
