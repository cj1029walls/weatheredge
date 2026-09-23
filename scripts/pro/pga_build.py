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
from archive import save_locked

print = functools.partial(print, flush=True)

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.join(ROOT, "scripts", "pga"))
from deep_history import canon_key, norm_player, get_json, SB_URL
from schedule import EVENTS

DEEP = os.path.join(ROOT, "data", "pga", "deep.json")
FREE = os.path.join(ROOT, "site", "pga", "data.json")
OUT = os.path.join(ROOT, "site", "pro", "pga.json")
ARCH = os.path.join(ROOT, "data", "pro", "pga_predictions")

from zoneinfo import ZoneInfo
ET = ZoneInfo("America/New_York")  # real Eastern time: a fixed UTC-4 is an hour off from Nov 1 (DST ends)
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
    # Team match-play weeks (Presidents/Ryder Cup) are skipped: stroke-play
    # course-horse and field-percentile wind leans mean nothing there, and a
    # 24-man "top-20 finish" grade would inflate the public record.
    today = datetime.now(ET).date()
    for ev in EVENTS:
        if ev.get("team"):
            continue
        r1 = datetime.strptime(ev["r1"], "%Y-%m-%d").date()
        end = datetime.strptime(ev["end"], "%Y-%m-%d").date()
        if r1 - timedelta(days=8) <= today <= end + timedelta(days=1):
            return ev
    future = [e for e in EVENTS if not e.get("team")
              and datetime.strptime(e["r1"], "%Y-%m-%d").date() > today]
    return min(future, key=lambda e: e["r1"]) if future else None


def team_week():
    """The team match-play event (Presidents/Ryder Cup) being played this week, if any."""
    today = datetime.now(ET).date()
    for e in EVENTS:
        if not e.get("team"):
            continue
        r1 = datetime.strptime(e["r1"], "%Y-%m-%d").date()
        end = datetime.strptime(e["end"], "%Y-%m-%d").date()
        if r1 - timedelta(days=4) <= today <= end:
            return e
    return None


def _days_apart(a, b):
    try:
        return abs((datetime.strptime(a, "%Y-%m-%d") - datetime.strptime(b, "%Y-%m-%d")).days)
    except ValueError:
        return 99


def fetch_field(ev_key, year, r1=None):
    """This week's field from ESPN's current-season scoreboard, if posted."""
    try:
        sb = get_json(SB_URL.format(y=year), tries=2)
    except Exception as e:
        print(f"field: espn unavailable ({e})")
        return []
    evs = sb.get("events") or []
    hit = next((e for e in evs if canon_key(e.get("name") or "") == ev_key), None)
    if hit is None and r1:
        # Name drift must not silently zero the field (Sept 2026: ESPN's
        # "Biltmore Championship Asheville" keyed differently from ours and the
        # board said the field wasn't posted). Fall back to the single ESPN
        # event starting within a day of our round 1 — and say so loudly.
        near = [e for e in evs if _days_apart((e.get("date") or "")[:10], r1) <= 1]
        if len(near) == 1:
            hit = near[0]
        if near:
            print(f"::warning::PGA field: no ESPN event keys to '{ev_key}'"
                  + (f"; using '{hit.get('name')}' (same start date) — add a CANON anchor" if hit
                     else f"; same-week candidates: {[e.get('name') for e in near]}"))
    if hit is None:
        return []
    comps = hit.get("competitions") or []
    rows = comps[0].get("competitors") if comps else []
    return [norm_player((c.get("athlete") or {}).get("displayName") or "")
            for c in (rows or []) if (c.get("athlete") or {}).get("displayName")]


def main():
    deep = json.load(open(DEEP)) if os.path.exists(DEEP) else {}
    players = deep.get("players") or {}
    events = deep.get("events") or {}
    print(f"deep layer: {len(events)} events · {len(players)} players")

    ev = current_event()
    if not ev:
        json.dump(dict(updated=datetime.now(ET).strftime("%Y-%m-%d %H:%M ET"),
                       event=None, seasonComplete=True,
                       note=f"Season complete — the PRO board returns with the first "
                            f"{int(EVENTS[-1]['end'][:4]) + 1} event in January."),
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
    # The free radar's rounds belong to ITS current event. In a team-event week
    # this board is already on the next stroke-play event, so the free rounds
    # (the Presidents Cup's forecast) must not be read as this event's.
    same_event = ((free.get("event") or {}).get("name") == ev["name"])
    rounds = (free.get("rounds") or []) if same_event else []
    fc_winds = [r.get("wind") for r in rounds if r.get("inWindow") and r.get("wind") is not None]
    wind_week = any(w >= WINDY_FC for w in fc_winds)
    waves = [dict(name=r.get("name"), am=r.get("am"), pm=r.get("pm"))
             for r in rounds if r.get("inWindow") and r.get("am")]

    field = fetch_field(key, year, ev["r1"])
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
    tw = team_week()
    if tw and tw is not ev:
        notes.append(f"{tw['name']} week is team match play — no stroke-play board. This is "
                     f"next week's {ev['name']} board, posted early; its tee-time forecast "
                     f"joins once round 1 is inside the radar's window.")
    elif not same_event:
        notes.append("Tee-time forecast joins once round 1 is inside the radar's window.")
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
    try:
        from market import attach_outright_prices
        attach_outright_prices(out.get("leans", []), "golf")
    except Exception as e:
        print(f"outright join skipped ({e})")
    json.dump(out, open(OUT, "w"))
    print(f"wrote {OUT}: {len(course)} course rows · {len(leans)} leans")

    # Once the tournament has started, the first archived card is final —
    # a later refresh must not reshuffle picks the grader will score.
    started = bool(ev.get("r1") and
                   str(ev["r1"])[:10] <= datetime.now(ET).strftime("%Y-%m-%d"))
    save_locked(os.path.join(ARCH, f"{year}-{key}.json"),
                dict(built=out["updated"], event=ev["name"], key=key, year=year,
                     leans=leans),
                started, label="PGA archive")


if __name__ == "__main__":
    main()
