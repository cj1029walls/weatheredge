#!/usr/bin/env python3
"""NASCAR weekly build: next Cup race + green-flag forecast + rain/delay
outlook -> site/nascar/data.json.

Every remaining 2026 points race is on an oval — Cup cars don't race ovals
in the rain, so the rain number IS the story: delays push races into the
night or to Monday, which changes DFS slates entirely. We also track the
temp swing through the race window (grip goes up as the track cools).

Schedule is curated in scripts/nascar/schedule.py — no API dependency.

No third-party dependencies.
"""
import functools, json, os, sys, time, urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

print = functools.partial(print, flush=True)
sys.path.insert(0, os.path.dirname(__file__))
from schedule import RACES

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
OUT = os.path.join(ROOT, "site", "nascar", "data.json")

FC_URL = ("https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
          "&hourly=temperature_2m,wind_speed_10m,wind_gusts_10m,cloud_cover,"
          "precipitation_probability,relative_humidity_2m"
          "&temperature_unit=fahrenheit&wind_speed_unit=mph&timezone={tz}&forecast_days=16")

ET = timezone(timedelta(hours=-4))


def get_json(url, tries=5):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "dfsradar-build/1.0"})
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read())
        except Exception as e:
            if i == tries - 1:
                raise
            time.sleep(8 * (i + 1))
            print(f"    retry {i+1}/{tries}: {e}")


def sky_of(cloud, pp, hour):
    night = hour >= 20 or hour < 6
    if pp is not None and pp >= 55: return "Rain risk"
    if cloud is None: return "—"
    if cloud >= 85: return "Overcast"
    if cloud >= 45: return "Partly cloudy"
    return "Clear" if night else "Sunny"


def main():
    today = datetime.now(ET).date()
    nxt = next((r for r in RACES
                if datetime.strptime(r["date"], "%Y-%m-%d").date() >= today), None)
    on_deck = [r for r in RACES
               if datetime.strptime(r["date"], "%Y-%m-%d").date() > (
                   datetime.strptime(nxt["date"], "%Y-%m-%d").date() if nxt else today)][:3]

    payload = dict(generated=datetime.now(ET).strftime("%Y-%m-%d %H:%M ET"),
                   race=None, brief="",
                   onDeck=[dict(name=r["name"], track=r["track"], city=r["city"],
                                date=datetime.strptime(r["date"], "%Y-%m-%d").strftime("%a %b %-d"),
                                playoff=bool(r.get("playoff")))
                           for r in on_deck])

    if nxt:
        rdate = datetime.strptime(nxt["date"], "%Y-%m-%d").date()
        et_h, et_m = int(nxt["et"].split(":")[0]), int(nxt["et"].split(":")[1])
        race = dict(shape=nxt.get("shape"),
                    name=nxt["name"], track=nxt["track"], city=nxt["city"],
                    playoff=bool(nxt.get("playoff")),
                    day=rdate.strftime("%A, %B %-d"),
                    time=f"{et_h % 12 or 12}:{et_m:02d} PM ET",
                    inWindow=False)
        horizon = today + timedelta(days=15)
        if rdate <= horizon:
            fc = get_json(FC_URL.format(lat=nxt["lat"], lon=nxt["lon"],
                                        tz=nxt["tz"].replace("/", "%2F")))
            h = fc["hourly"]
            # green flag in track-local wall clock
            green_utc = datetime(rdate.year, rdate.month, rdate.day, et_h, et_m, tzinfo=ET)
            local = green_utc.astimezone(ZoneInfo(nxt["tz"]))
            want = local.strftime("%Y-%m-%dT%H")
            idx = next((i for i, t in enumerate(h["time"]) if t.startswith(want)), None)
            if idx is not None:
                race["inWindow"] = True
                hourly = []
                for off in range(-2, 5):
                    j = idx + off
                    if j < 0 or j >= len(h["time"]) or h["temperature_2m"][j] is None:
                        continue
                    hh = int(h["time"][j][11:13])
                    hourly.append(dict(
                        lab=f"{hh % 12 or 12} {'PM' if hh >= 12 else 'AM'}", fp=(off == 0),
                        t=round(h["temperature_2m"][j]), w=round(h["wind_speed_10m"][j]),
                        rain=None if h["precipitation_probability"][j] is None
                             else round(h["precipitation_probability"][j])))
                worst = max((x["rain"] or 0) for x in hourly) if hourly else 0
                temps = [x["t"] for x in hourly]
                race.update(
                    temp=round(h["temperature_2m"][idx]),
                    wind=round(h["wind_speed_10m"][idx]),
                    gust=round(h["wind_gusts_10m"][idx]),
                    rain=None if h["precipitation_probability"][idx] is None
                         else round(h["precipitation_probability"][idx]),
                    rh=None if h["relative_humidity_2m"][idx] is None
                       else round(h["relative_humidity_2m"][idx]),
                    sky=sky_of(h["cloud_cover"][idx], h["precipitation_probability"][idx], local.hour),
                    hourly=hourly,
                    tempSwing=(max(temps) - min(temps)) if temps else 0,
                    delay=dict(level=("clear" if worst < 20 else "watch" if worst < 45
                                      else "likely" if worst < 70 else "severe"), pct=worst))
                parts = [f"{nxt['name']} at {nxt['track']}: {race['temp']}° and "
                         f"{race['sky'].lower()} at the green flag, wind {race['wind']} mph"
                         f" (gusts {race['gust']})."]
                if worst >= 45:
                    parts.append(f"Rain is the story — {worst}% peak chance in the race window, "
                                 "and Cup cars don't run ovals in the rain. Delay or postponement risk is real.")
                elif worst >= 20:
                    parts.append(f"Some rain around ({worst}% peak) — worth watching, ovals don't run wet.")
                else:
                    parts.append("No rain threat — this one runs on time.")
                if race["tempSwing"] >= 12:
                    parts.append(f"Track cools {race['tempSwing']}° through the window — "
                                 "grip picks up late, watch for handling swings.")
                payload["brief"] = " ".join(parts)
        payload["race"] = race

    with open(OUT, "w") as f:
        json.dump(payload, f, separators=(",", ":"))
    print(f"Wrote {OUT}: {payload['race']['name'] if payload['race'] else 'no race'}"
          f" (inWindow={payload['race']['inWindow'] if payload['race'] else '-'})")


if __name__ == "__main__":
    main()
