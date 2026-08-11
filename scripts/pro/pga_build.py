#!/usr/bin/env python3
"""DFSRADAR PRO — PGA weekly board -> site/pro/pga.json

This week's tournament with the layers the leaderboard doesn't show:
  * COURSE HISTORY — every relevant player's past finishes at this event
    (field-percentile based, 2018-present, from data/pga/deep.json)
  * WIND PEDIGREE — how each player's results hold up in WINDY editions vs
    calm ones; activated as a lean section when this week forecasts wind
  * RECENT FORM — last-5-start percentile trend
  * WAVE WATCH — carries the free radar's AM/PM wave splits forward so the
    draw edge and player edges live on one card

Field list: ESPN's scoreboard for the current season includes this week's
event with its field once ESPN posts it (usually early in the week). Until
then the board shows course-history horses from the full player pool with a
note. All leans archived to data/pro/pga_predictions/ for public grading
against the final leaderboard.

Percentile: pos/field, lower is better — 1st of 156 = 0.6%, 30th of 30 = 100%.
Course/wind scores are shrunk toward the 50% field median (k=4 starts) so a
one-start wonder can't top the board.

No third-party dependencies.
"""
import functools, json, os, re, sys, time, unicodedata, urllib.request
from datetime import datetime, timedelta, timezone

print = functools.partial(print, flush=True)

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.join(ROOT, "scripts", "pga"))
from deep_history import canon_key, norm_player, get_json, SB_URL
from schedule import EVENTS

DEEP = os.path.join(ROOT, "data", "pga", "deep.json")
FREE = os.path.join(ROOT, "site", "pga", "data.json")
OUT = os.path.join(ROOT, "site", "pro", "pga.json")
ARCH = os.path.join(ROOT, "data", "pro", "pga_predictions")

ET = timezone(timedelta(hours=-4))
SHRINK_K = 4          # starts of shrinkage toward field median
WINDY_FC = 12         # forecast round avg wind ≥ this -> wind week


def pctile(pos, n):
    return round(100 * pos / max(n, 1), 1)


def shrunk_avg(pcts, k=SHRINK_K, prior=50.0):
    n = len(pcts)
    if not n:
        return None
    return round((sum(pcts) + prior * k) / (n + k), 1)


def current_event():
    today = datetime.now(ET).date()
    for ev in EVENTS:
        r1 = datetime.strptime(ev["r1"], "%Y-%m-%d").date()
        end = datetime.strptime(ev["end"], "%Y-%m-%d").date()
        if r1 - timedelta(days=8) <= today <= end + timedelta(days=1):
            return ev
    future = [e for e in EVENTS
              if datetime.strptime(e["r1"], "%Y-%m-%d").date() > today]
    return min(future, key=lambda e: e["r1"]) if future else None


def fetch_field(ev_key, year):
    """This week's field from ESPN's current-season scoreboard, if posted."""
    try:
        sb = get_json(SB_URL.format(y=year), tries=2)
    except Exception as e:
        print(f"field: espn unavailable ({e})")
        return []
    for e in (sb.get("events") or []):
        if canon_key(e.get("name") or "") != ev_key:
            continue
        comps = e.get("competitions") or []
        rows = comps[0].get("competitors") if comps else []
        return [norm_player((c.get("athlete") or {}).get("displayName") or "")
                for c in (rows or []) if (c.get("athlete") or {}).get("displayName")]
    return []


def main():
    deep = json.load(open(DEEP)) if os.path.exists(DEEP) else {}
    players = deep.get("players") or {}
    events = deep.get("events") or {}
    print(f"deep layer: {len(events)} events · {len(players)} players")

    ev = current_event()
    if not ev:
        json.dump(dict(updated=datetime.now(ET).strftime("%Y-%m-%d %H:%M ET"),
                       event=None, note="No upcoming tournament on the schedule."),
                  open(OUT, "w"))
        print("no event — wrote empty board")
        return
    key = canon_key(ev["name"])
    year = int(ev["r1"][:4])
    print(f"event: {ev['name']} -> key {key}")

    # windy edition lookup for THIS event key
    ev_hist = events.get(key) or {}
    editions = ev_hist.get("editions") or {}

    free = {}
    if os.path.exists(FREE):
        try:
            free = json.load(open(FREE))
        except Exception:
            free = {}
    rounds = free.get("rounds") or []
    fc_winds = [r.get("wind") for r in rounds if r.get("inWindow") and r.get("wind") is not None]
    wind_week = any(w >= WINDY_FC for w in fc_winds)
    waves = [dict(name=r.get("name"), am=r.get("am"), pm=r.get("pm"))
             for r in rounds if r.get("inWindow") and r.get("am")]

    field = fetch_field(key, year)
    field_set = set(field)
    print(f"field: {len(field)} players posted · wind week: {wind_week}")

    def rows_of(p):
        return players.get(p) or []

    pool = field if field else list(players.keys())

    # ---- course history board
    course = []
    for p in pool:
        here = [r for r in rows_of(p) if r[0] == key]
        if len(here) < 2:
            continue
        pcts = [pctile(r[2], r[3]) for r in here]
        course.append(dict(
            player=p, starts=len(here),
            score=shrunk_avg(pcts),
            best=min(r[2] for r in here),
            avgFin=round(sum(r[2] for r in here) / len(here), 1),
            last=[dict(y=r[1], pos=r[2], n=r[3]) for r in here[-4:]][::-1],
            inField=(p in field_set) if field else None))
    course.sort(key=lambda c: c["score"])
    course = course[:25]

    # ---- wind pedigree (across all weather-tagged events)
    wind_rows = []
    for p in pool:
        wp, cp = [], []
        for r in rows_of(p):
            ed = (events.get(r[0]) or {}).get("editions", {}).get(str(r[1]))
            if not ed or ed.get("wind") is None:
                continue
            (wp if ed.get("windy") else cp).append(pctile(r[2], r[3]))
        if len(wp) >= 6 and len(cp) >= 6:
            ws, cs = shrunk_avg(wp, k=2), shrunk_avg(cp, k=2)
            wind_rows.append(dict(player=p, windStarts=len(wp), calmStarts=len(cp),
                                  windScore=ws, calmScore=cs,
                                  delta=round(cs - ws, 1),
                                  inField=(p in field_set) if field else None))
    wind_rows.sort(key=lambda w: -w["delta"])
    wind_proof = wind_rows[:12]
    wind_fade = sorted(wind_rows, key=lambda w: w["delta"])[:8]

    # ---- recent form
    form = []
    for p in pool:
        rows = rows_of(p)
        recent = rows[-5:]
        if len(recent) < 3:
            continue
        pcts = [pctile(r[2], r[3]) for r in recent]
        form.append(dict(player=p, starts=len(recent),
                         score=round(sum(pcts) / len(pcts), 1),
                         last=[dict(ev=r[0], y=r[1], pos=r[2], n=r[3])
                               for r in recent][::-1],
                         inField=(p in field_set) if field else None))
    form.sort(key=lambda f: f["score"])
    form = form[:20]

    # ---- leans
    leans = []
    form_rank = {f["player"]: i for i, f in enumerate(form)}
    for c in course[:8]:
        if field and not c["inField"]:
            continue
        if c["score"] > 42:            # worse than ~field median even shrunk — no target
            continue
        why = (f"{c['starts']} starts here · avg finish {c['avgFin']} · best {c['best']}"
               + (f" · top-20 recent form" if form_rank.get(c["player"], 99) < 20 else ""))
        leans.append(dict(k="COURSE HORSE", side="TARGET", who=c["player"], why=why,
                          score=c["score"]))
        if len([l for l in leans if l["k"] == "COURSE HORSE"]) >= 5:
            break
    if wind_week:
        for w in wind_proof[:5]:
            if field and not w["inField"]:
                continue
            leans.append(dict(k="WIND WEEK", side="TARGET", who=w["player"],
                why=f"finishes {w['delta']} pts better (field pctile) in windy editions · {w['windStarts']} windy starts"))
        for w in wind_fade[:3]:
            if field and not w["inField"]:
                continue
            if w["delta"] <= -6:
                leans.append(dict(k="WIND WEEK", side="FADE", who=w["player"],
                    why=f"finishes {abs(w['delta'])} pts worse in windy editions · {w['windStarts']} windy starts"))

    notes = []
    if not field:
        notes.append("ESPN hasn't posted this week's field yet — boards show the "
                     "full player pool; they filter to the field when it posts.")
    if not wind_week and fc_winds:
        notes.append(f"Calm forecast (round winds {min(fc_winds)}–{max(fc_winds)} mph) — "
                     "wind-pedigree leans activate at 12+ mph.")
    ed_tagged = sum(1 for e2 in editions.values() if e2.get("wind") is not None)
    hist_note = (f"{len(editions)} past editions on file ({ed_tagged} weather-tagged)"
                 if editions else "First year on file for this event — course history builds from here.")

    out = dict(
        updated=datetime.now(ET).strftime("%Y-%m-%d %H:%M ET"),
        event=dict(name=ev["name"], course=ev["course"], city=ev["city"],
                   r1=ev["r1"], end=ev["end"], key=key, histNote=hist_note),
        windWeek=wind_week, fcWinds=fc_winds, waves=waves,
        fieldN=len(field), course=course, wind=dict(proof=wind_proof, fade=wind_fade),
        form=form, leans=leans, note=" ".join(notes))
    json.dump(out, open(OUT, "w"))
    print(f"wrote {OUT}: {len(course)} course rows · {len(leans)} leans")

    os.makedirs(ARCH, exist_ok=True)
    json.dump(dict(built=out["updated"], event=ev["name"], key=key, year=year,
                   leans=leans),
              open(os.path.join(ARCH, f"{year}-{key}.json"), "w"))
    print("archived predictions")


if __name__ == "__main__":
    main()
