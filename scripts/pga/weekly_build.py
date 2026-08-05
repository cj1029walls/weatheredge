#!/usr/bin/env python3
"""PGA weekly build: this week's tournament + round-by-round forecasts with
AM/PM tee-time wave splits -> site/pga/data.json.

The golf DFS edge: half the field tees off early, half late. When wind (or
rain) is lopsided between waves, one half of the field plays a different golf
course. We quantify that per round from the hourly forecast.

Waves: AM ≈ 7:00-12:00 local, PM ≈ 12:00-18:00 local.
Schedule is curated in scripts/pga/schedule.py — no API dependency.

No third-party dependencies.
"""
import functools, json, os, statistics, sys, time, urllib.request
from datetime import date, datetime, timedelta, timezone

print = functools.partial(print, flush=True)
sys.path.insert(0, os.path.dirname(__file__))
from schedule import EVENTS

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
OUT = os.path.join(ROOT, "site", "pga", "data.json")

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


def sky_of(cloud, pp):
    if pp is not None and pp >= 55: return "Rain risk"
    if cloud is None: return "—"
    if cloud >= 85: return "Overcast"
    if cloud >= 45: return "Partly cloudy"
    return "Sunny"


def wave_stats(rows):
    """rows: list of (hour, temp, wind, gust, rain, cloud)"""
    if not rows:
        return None
    return dict(wind=round(statistics.mean(r[2] for r in rows)),
                gust=round(max(r[3] for r in rows)),
                temp=round(statistics.mean(r[1] for r in rows)),
                rain=round(max((r[4] or 0) for r in rows)))


def main():
    today = datetime.now(ET).date()
    current = next((e for e in EVENTS
                    if datetime.strptime(e["end"], "%Y-%m-%d").date() >= today), None)
    upcoming = [e for e in EVENTS
                if datetime.strptime(e["r1"], "%Y-%m-%d").date() > today
                and e is not current][:3]

    payload = dict(generated=datetime.now(ET).strftime("%Y-%m-%d %H:%M ET"),
                   event=None, rounds=[], waves=[], brief="",
                   onDeck=[dict(name=e["name"], course=e["course"], city=e["city"],
                                dates=f"{datetime.strptime(e['r1'],'%Y-%m-%d').strftime('%b %-d')}–{datetime.strptime(e['end'],'%Y-%m-%d').strftime('%-d')}")
                           for e in upcoming])

    if current:
        r1 = datetime.strptime(current["r1"], "%Y-%m-%d").date()
        end = datetime.strptime(current["end"], "%Y-%m-%d").date()
        payload["event"] = dict(hole=current.get("hole"),
                                name=current["name"], course=current["course"],
                                city=current["city"], team=current["team"],
                                dates=f"{r1.strftime('%b %-d')}–{end.strftime('%-d')}",
                                r1=current["r1"], end=current["end"])
        horizon = today + timedelta(days=15)
        if r1 <= horizon:
            fc = get_json(FC_URL.format(lat=current["lat"], lon=current["lon"],
                                        tz=current["tz"].replace("/", "%2F")))
            h = fc["hourly"]
            by_day = {}
            for i, t in enumerate(h["time"]):
                d, hr = t[:10], int(t[11:13])
                if not (6 <= hr <= 19):
                    continue
                vals = (hr, h["temperature_2m"][i], h["wind_speed_10m"][i],
                        h["wind_gusts_10m"][i], h["precipitation_probability"][i],
                        h["cloud_cover"][i])
                if any(v is None for v in vals[1:4]):
                    continue
                by_day.setdefault(d, []).append(vals)

            names = ["Round 1 · Thu", "Round 2 · Fri", "Round 3 · Sat", "Round 4 · Sun"]
            d = r1
            ri = 0
            while d <= end:
                key = d.isoformat()
                rows = by_day.get(key, [])
                rd = dict(name=names[ri] if ri < 4 else f"Day {ri+1}",
                          date=d.strftime("%a %b %-d"), inWindow=bool(rows))
                if rows:
                    am = wave_stats([r for r in rows if 7 <= r[0] < 12])
                    pm = wave_stats([r for r in rows if 12 <= r[0] < 18])
                    allday = wave_stats(rows)
                    worst_rain = allday["rain"]
                    rd.update(
                        temp=allday["temp"], wind=allday["wind"], gust=allday["gust"],
                        rain=worst_rain,
                        sky=sky_of(statistics.mean((r[5] or 0) for r in rows),
                                   worst_rain),
                        delay=("clear" if worst_rain < 20 else "watch" if worst_rain < 45
                               else "likely" if worst_rain < 70 else "severe"),
                        am=am, pm=pm,
                        hourly=[dict(lab=f"{r[0]%12 or 12}{'a' if r[0]<12 else 'p'}",
                                     t=round(r[1]), w=round(r[2]),
                                     rain=None if r[4] is None else round(r[4]))
                                for r in rows if 7 <= r[0] <= 18])
                    if am and pm and ri < 2:      # wave edge matters Thu/Fri (split waves)
                        diff = pm["wind"] - am["wind"]
                        if abs(diff) >= 4:
                            rd["waveEdge"] = dict(
                                calmer="AM" if diff > 0 else "PM", diff=abs(diff),
                                txt=f"{'PM' if diff>0 else 'AM'} wave faces {abs(diff)} mph more wind — "
                                    f"edge to the {'morning' if diff>0 else 'afternoon'} wave")
                        elif am["rain"] - pm["rain"] >= 25 or pm["rain"] - am["rain"] >= 25:
                            wetter = "AM" if am["rain"] > pm["rain"] else "PM"
                            rd["waveEdge"] = dict(
                                calmer="PM" if wetter == "AM" else "AM",
                                diff=abs(am["rain"] - pm["rain"]),
                                txt=f"{wetter} wave carries the rain risk — edge to the "
                                    f"{'afternoon' if wetter=='AM' else 'morning'} wave")
                payload["rounds"].append(rd)
                d += timedelta(days=1)
                ri += 1

            # brief
            parts = []
            inw = [r for r in payload["rounds"] if r.get("inWindow")]
            if inw:
                windy = max(inw, key=lambda r: r["wind"])
                if windy["wind"] >= 12:
                    parts.append(f"{windy['name'].split(' · ')[0]} is the wind day — "
                                 f"{windy['wind']} mph average, gusts to {windy['gust']}.")
                edges = [r for r in inw if r.get("waveEdge")]
                for r in edges[:2]:
                    parts.append(f"{r['name'].split(' · ')[0]}: {r['waveEdge']['txt']}.")
                wet = [r for r in inw if r["rain"] >= 45]
                if wet:
                    parts.append("Rain watch: " + ", ".join(f"{r['name'].split(' · ')[0]} ({r['rain']}%)"
                                                            for r in wet) + ".")
                elif not edges:
                    parts.append("No serious weather separation this week — waves play close to even.")
            payload["brief"] = " ".join(parts)
        else:
            payload["brief"] = ""

    with open(OUT, "w") as f:
        json.dump(payload, f, separators=(",", ":"))
    ev = payload["event"]["name"] if payload["event"] else "no event"
    print(f"Wrote {OUT}: {ev}, {len([r for r in payload['rounds'] if r.get('inWindow')])} rounds in window")


if __name__ == "__main__":
    main()
