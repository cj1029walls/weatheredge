#!/usr/bin/env python3
"""DFSRADAR PRO — NASCAR weekly board -> site/pro/nascar.json

This week's race with the layers the entry list doesn't show:
  * TRACK HISTORY — every driver's finishes at this track (2018-present,
    from data/nascar/deep.json), with the Next Gen era (2022+) split out —
    the car changed in 2022 and old-car track records mislead
  * TRACK-TYPE FORM — driver form on this track's TYPE (superspeedway /
    intermediate / short / flat / road), last 10 such races since 2022
  * HEAT EDGE — drivers who over/under-perform when the track runs hot
    (race-day high ≥ 88° = slick track), activated when the forecast is hot
  * DELAY CONTEXT — carries the free radar's rain/delay outlook forward

All leans archived to data/pro/nascar_predictions/ for public grading
against the finishing order.

No third-party dependencies.
"""
import functools, json, os, re, sys
from datetime import datetime, timedelta, timezone

print = functools.partial(print, flush=True)

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.join(ROOT, "scripts", "nascar"))
from deep_history import track_of
from schedule import RACES

DEEP = os.path.join(ROOT, "data", "nascar", "deep.json")
FREE = os.path.join(ROOT, "site", "nascar", "data.json")
OUT = os.path.join(ROOT, "site", "pro", "nascar.json")
ARCH = os.path.join(ROOT, "data", "pro", "nascar_predictions")

ET = timezone(timedelta(hours=-4))
NG_YEAR = 2022        # Next Gen car era
HOT_FC = 88           # forecast high ≥ this -> heat leans active


def avg(v):
    return round(sum(v) / len(v), 1) if v else None


def main():
    deep = json.load(open(DEEP)) if os.path.exists(DEEP) else {}
    drivers = deep.get("drivers") or {}
    tracks = deep.get("tracks") or {}
    print(f"deep layer: {len(drivers)} drivers · "
          f"{len(deep.get('races') or [])} races")

    today = datetime.now(ET).date()
    nxt = None
    for r in RACES:
        d = datetime.strptime(r["date"], "%Y-%m-%d").date()
        if d >= today:
            nxt = r
            break
    if not nxt:
        json.dump(dict(updated=datetime.now(ET).strftime("%Y-%m-%d %H:%M ET"),
                       race=None, note="No upcoming race on the schedule."),
                  open(OUT, "w"))
        print("no race — wrote empty board")
        return

    tk = track_of(nxt["track"]) or track_of(nxt["name"])
    key, ttype = (tk[0], tk[1]) if tk else (None, None)
    print(f"race: {nxt['name']} at {nxt['track']} -> {key} ({ttype})")

    free = {}
    if os.path.exists(FREE):
        try:
            free = json.load(open(FREE))
        except Exception:
            free = {}
    fr = free.get("race") or {}
    fc_temp = fr.get("temp")
    hot_fc = fc_temp is not None and fc_temp >= HOT_FC
    delay = fr.get("delay")

    # ---- track history (active = raced in the current season on file)
    cur_season = max((r["y"] for r in (deep.get("races") or [])), default=NG_YEAR)
    board = []
    for drv, rows in drivers.items():
        here = [r for r in rows if r[0] == key]
        recent_any = [r for r in rows if r[1] >= NG_YEAR]
        if len(here) < 2 or len(recent_any) < 10:
            continue                      # drivers with a real track sample
        if not any(r[1] >= cur_season for r in rows):
            continue                      # retired / not racing this season
        ng = [r for r in here if r[1] >= NG_YEAR]
        fins = [r[2] for r in here]
        ngf = [r[2] for r in ng]
        board.append(dict(
            driver=drv, starts=len(here),
            avgFin=avg(fins), best=min(fins),
            top5=sum(1 for f in fins if f <= 5),
            ngStarts=len(ng), ngAvg=avg(ngf),
            last=[dict(y=r[1], pos=r[2]) for r in here[-4:]][::-1]))
    board.sort(key=lambda b: (b["ngAvg"] if b["ngAvg"] is not None else b["avgFin"]))
    board = board[:26]

    # ---- track-type form (Next Gen era, last 10 of this type)
    tform = []
    for drv, rows in drivers.items():
        if not any(r[1] >= cur_season for r in rows):
            continue
        typ = [r for r in rows
               if r[1] >= NG_YEAR and (tracks.get(r[0]) or {}).get("type") == ttype]
        if len(typ) < 6:
            continue
        last10 = typ[-10:]
        tform.append(dict(driver=drv, n=len(last10),
                          avgFin=avg([r[2] for r in last10]),
                          top5=sum(1 for r in last10 if r[2] <= 5)))
    tform.sort(key=lambda t: t["avgFin"])
    tform = tform[:20]

    # ---- heat edge (all tracks, hot vs not)
    heat = []
    for drv, rows in drivers.items():
        recent_any = [r for r in rows if r[1] >= NG_YEAR]
        if len(recent_any) < 10 or not any(r[1] >= cur_season for r in rows):
            continue
        hot = [r[2] for r in rows if r[4] == 1]
        cool = [r[2] for r in rows if r[4] == 0]
        if len(hot) >= 8 and len(cool) >= 8:
            d = round(avg(cool) - avg(hot), 1)   # positive = better when hot
            heat.append(dict(driver=drv, hotN=len(hot), hotAvg=avg(hot),
                             coolAvg=avg(cool), delta=d))
    heat.sort(key=lambda h: -h["delta"])
    heat_up = heat[:10]
    heat_dn = sorted(heat, key=lambda h: h["delta"])[:8]

    # ---- leans
    leans = []
    tf_rank = {t["driver"]: i for i, t in enumerate(tform)}
    for b in board[:6]:
        eff = b["ngAvg"] if b["ngAvg"] is not None else b["avgFin"]
        if eff > 12:                   # back-half average — not a target
            continue
        why = (f"{b['avgFin']} avg finish here ({b['starts']} starts, {b['top5']} top-5s)"
               + (f" · {b['ngAvg']} avg in the Next Gen car" if b["ngAvg"] is not None else "")
               + (f" · top-10 {ttype} form" if tf_rank.get(b["driver"], 99) < 10 else ""))
        leans.append(dict(k="TRACK TARGET", side="TARGET", who=b["driver"], why=why))
        if len(leans) >= 5:
            break
    dom = sorted(board, key=lambda b: -b["top5"])[:1]
    if dom and dom[0]["top5"] >= 3:
        b = dom[0]
        leans.append(dict(k="DOMINATOR", side="TARGET", who=b["driver"],
            why=f"{b['top5']} top-5s in {b['starts']} starts here · best finish {b['best']}"))
    if hot_fc:
        for h in heat_up[:4]:
            if h["delta"] >= 2:
                leans.append(dict(k="HEAT EDGE", side="TARGET", who=h["driver"],
                    why=f"forecast {fc_temp}° · finishes {h['delta']} spots better in hot races ({h['hotN']} hot starts)"))
        for h in heat_dn[:3]:
            if h["delta"] <= -2:
                leans.append(dict(k="HEAT EDGE", side="FADE", who=h["driver"],
                    why=f"forecast {fc_temp}° · finishes {abs(h['delta'])} spots worse in hot races ({h['hotN']} hot starts)"))

    notes = []
    hist_n = len([r for r in (deep.get("races") or []) if r.get("track") == key])
    if hist_n:
        notes.append(f"{hist_n} past races at this track on file (2018-present).")
    else:
        notes.append("First race at this track on file — the board leans on track-type form.")
    if not hot_fc and fc_temp is not None:
        notes.append(f"Forecast high {fc_temp}° — heat leans activate at {HOT_FC}°+.")

    out = dict(
        updated=datetime.now(ET).strftime("%Y-%m-%d %H:%M ET"),
        race=dict(name=nxt["name"], track=nxt["track"], city=nxt["city"],
                  date=nxt["date"], time=nxt.get("et"), key=key, type=ttype,
                  playoff=bool(nxt.get("playoff"))),
        fcTemp=fc_temp, hotFc=hot_fc, delay=delay,
        board=board, tform=tform,
        heat=dict(up=heat_up, dn=heat_dn),
        leans=leans, note=" ".join(notes))
    try:
        from market import attach_outright_prices
        attach_outright_prices(out.get("leans", []), "nascar")
    except Exception as e:
        print(f"outright join skipped ({e})")
    json.dump(out, open(OUT, "w"))
    print(f"wrote {OUT}: {len(board)} board rows · {len(leans)} leans")

    os.makedirs(ARCH, exist_ok=True)
    json.dump(dict(built=out["updated"], race=nxt["name"], key=key,
                   date=nxt["date"], leans=leans),
              open(os.path.join(ARCH, f"{nxt['date']}-{key}.json"), "w"))
    print("archived predictions")


if __name__ == "__main__":
    main()
