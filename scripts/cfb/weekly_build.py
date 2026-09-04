#!/usr/bin/env python3
"""CFB weekly slate build: upcoming FBS games + kickoff forecasts + similar-
weather venue history -> site/cfb/data.json (consumed by site/cfb/index.html).

Schedule + betting totals from CollegeFootballData.com (CFBD_API_KEY).
Weather from Open-Meteo (16-day horizon). History from
data/cfb/venues_history.json (Power 4 home venues, real closing totals).

Games at Power 4 venues get the full treatment (similar-weather O/U vs each
matched game's own closing total). Other FBS games still show kickoff
forecast, rain/delay outlook, and today's total — forecast-only, no history.

Matching is wind-SPEED based (no field bearings curated for CFB yet).

No third-party dependencies.
"""
import argparse, functools, json, os, statistics, sys, time
import urllib.error, urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

print = functools.partial(print, flush=True)

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
HISTORY = os.path.join(ROOT, "data", "cfb", "venues_history.json")
OUT = os.path.join(ROOT, "site", "cfb", "data.json")

CFBD = "https://api.collegefootballdata.com"
FC_URL = ("https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
          "&hourly=temperature_2m,dew_point_2m,wind_speed_10m,wind_direction_10m,"
          "cloud_cover,precipitation_probability,relative_humidity_2m,surface_pressure"
          "&temperature_unit=fahrenheit&wind_speed_unit=mph&timezone=UTC&forecast_days=16")

P4 = {"SEC", "Big Ten", "Big 12", "ACC"}
# Real Eastern zone — a fixed -4 offset mislabels every kickoff after DST ends.
ET = ZoneInfo("America/New_York")

# Box-score metrics carried through from the history build. Each is reported
# against two baselines (all FBS games at P4 venues, and this venue's own
# history) and suppressed entirely when the matched sample is too thin.
METRICS = (
    ("pts", "SCORING", 0),
    ("pa",  "PASSING YDS", 0),
    ("ru",  "RUSHING YDS", 0),
    ("cp",  "COMPLETION %", 1),
    ("fg",  "FG MAKES", 1),
    ("fl",  "FUMBLES", 1),
)
MIN_METRIC_N = 12          # below this we show the count, not a percentage


def gv(d, *names):
    for n in names:
        if n in d and d[n] is not None:
            return d[n]
    return None


def get_json(url, tries=5, auth=False):
    hdrs = {"User-Agent": "dfsradar-build/1.0", "Accept": "application/json"}
    if auth:
        key = os.environ.get("CFBD_API_KEY")
        if not key:
            raise SystemExit("CFBD_API_KEY not set")
        hdrs["Authorization"] = f"Bearer {key}"
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read())
        except Exception as e:
            if i == tries - 1:
                raise
            wait = 45 if (isinstance(e, urllib.error.HTTPError) and e.code == 429) else 8 * (i + 1)
            print(f"    retry {i+1}/{tries} in {wait}s: {e}")
            time.sleep(wait)


def season_year(now):
    return now.year if now.month >= 2 else now.year - 1


def load_upcoming(window_days=8):
    now = datetime.now(timezone.utc)
    yr = season_year(datetime.now(ET))
    end = now + timedelta(days=window_days)
    out = []
    for st in ("regular", "postseason"):
        try:
            games = get_json(f"{CFBD}/games?year={yr}&seasonType={st}", auth=True)
        except Exception as e:
            if st == "postseason":
                continue           # not published until December
            raise
        for g in games:
            start = gv(g, "startDate", "start_date")
            if not start:
                continue
            hp = gv(g, "homePoints", "home_points")
            if hp is not None or gv(g, "completed"):
                continue
            hc = (gv(g, "homeClassification", "home_division") or "").lower()
            ac = (gv(g, "awayClassification", "away_division") or "").lower()
            if hc != "fbs" and ac != "fbs":
                continue
            # FBS-vs-FCS games behave differently (blowouts, running clocks) and
            # weather moves them less — worth flagging rather than silently mixing in.
            g["_fcs"] = (hc == "fcs" or ac == "fcs")
            try:
                utc = datetime.fromisoformat(start.replace("Z", "+00:00"))
            except ValueError:
                continue
            if not (now - timedelta(hours=6) <= utc <= end):
                continue
            g["_utc"] = utc
            g["_season_type"] = st
            out.append(g)
    print(f"upcoming FBS games in window: {len(out)}")
    return out, yr


def fetch_totals(yr, season_types):
    out = {}
    for st in season_types:
        try:
            recs = get_json(f"{CFBD}/lines?year={yr}&seasonType={st}", auth=True)
        except Exception as e:
            print(f"lines {st} unavailable ({e})")
            continue
        for rec in recs:
            gid = gv(rec, "id", "gameId", "game_id")
            ous = [gv(l, "overUnder", "over_under") for l in rec.get("lines", [])]
            ous = [float(x) for x in ous if x is not None]
            if gid and ous:
                out[gid] = statistics.median(ous)
    print(f"cfbd lines: totals for {len(out)} games")
    return out


_TEAM_INFO = None
def team_info(yr):
    """{school: {lat, lon, logo, color, ab}} from /teams/fbs — travel badges
    plus the branding (logo/color/abbreviation) the 3D stadium view uses."""
    global _TEAM_INFO
    if _TEAM_INFO is None:
        _TEAM_INFO = {}
        try:
            for t in get_json(f"{CFBD}/teams/fbs?year={yr}", auth=True):
                loc = gv(t, "location") or {}
                logos = gv(t, "logos") or []
                _TEAM_INFO[gv(t, "school")] = dict(
                    lat=gv(loc, "latitude"), lon=gv(loc, "longitude"),
                    logo=(logos[0] if logos else None),
                    color=gv(t, "color"), ab=gv(t, "abbreviation"))
        except Exception as e:
            print(f"team info unavailable ({e})")
    return _TEAM_INFO


def team_locations(yr):
    return {k: (v["lat"], v["lon"]) for k, v in team_info(yr).items()
            if v["lat"] is not None and v["lon"] is not None}


def miles(a_lat, a_lon, b_lat, b_lon):
    from math import radians, sin, cos, asin, sqrt
    la1, lo1, la2, lo2 = map(radians, (a_lat, a_lon, b_lat, b_lon))
    h = sin((la2 - la1) / 2) ** 2 + cos(la1) * cos(la2) * sin((lo2 - lo1) / 2) ** 2
    return 3956 * 2 * asin(sqrt(h))


def elev_feet(v):
    """CFBD venue elevation, unit-ambiguous — normalize to feet."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if v >= 2600 else v * 3.28084


_VENUES = None
def venue_meta(vid):
    global _VENUES
    if _VENUES is None:
        _VENUES = {v["id"]: v for v in get_json(f"{CFBD}/venues", auth=True)}
    return _VENUES.get(vid)


_FC = {}
def forecast(lat, lon):
    k = (round(lat, 3), round(lon, 3))
    if k not in _FC:
        _FC[k] = get_json(FC_URL.format(lat=lat, lon=lon))
        time.sleep(0.8)
    return _FC[k]


def sky_of(cloud, pp, hour):
    night = hour >= 20 or hour < 6
    if pp is not None and pp >= 55: return ("🌧️", "Rain risk")
    if cloud is None: return ("🌤️", "—")
    if cloud >= 85: return ("☁️", "Overcast")
    if cloud >= 45: return ("🌙", "Partly cloudy") if night else ("⛅", "Partly cloudy")
    return ("🌙", "Clear") if night else ("☀️", "Sunny")


def wind_receptivity(games):
    if len(games) < 40:
        return None
    xs = [g["w"] for g in games]; ys = [g["pts"] for g in games]
    n = len(xs); mx, my = sum(xs)/n, sum(ys)/n
    sxx = sum((x-mx)**2 for x in xs)
    if not sxx or not my:
        return None
    slope = sum((x-mx)*(y-my) for x, y in zip(xs, ys)) / sxx
    pct10 = round(slope * 10 / my * 100)
    a = abs(pct10)
    rating = "LOW" if a < 4 else "MEDIUM" if a < 8 else "HIGH" if a < 13 else "EXTREME"
    return dict(rating=rating, pct10=pct10)


def feels_like(temp, rh, wind):
    """Heat index when it's warm and humid, wind chill when it's cold and windy.

    Both are the standard NWS formulas; outside their valid ranges the honest
    answer is just the air temperature.
    """
    if temp is None:
        return None
    if temp >= 80 and rh is not None:
        t, r = float(temp), float(rh)
        hi = (-42.379 + 2.04901523 * t + 10.14333127 * r
              - 0.22475541 * t * r - 0.00683783 * t * t
              - 0.05481717 * r * r + 0.00122874 * t * t * r
              + 0.00085282 * t * r * r - 0.00000199 * t * t * r * r)
        if r < 13 and 80 <= t <= 112:
            hi -= ((13 - r) / 4) * ((17 - abs(t - 95)) / 17) ** 0.5
        elif r > 85 and 80 <= t <= 87:
            hi += ((r - 85) / 10) * ((87 - t) / 5)
        return round(max(hi, t))
    if temp <= 50 and wind and wind >= 3:
        t, v = float(temp), float(wind)
        wc = 35.74 + 0.6215 * t - 35.75 * v ** 0.16 + 0.4275 * t * v ** 0.16
        return round(min(wc, t))
    return round(temp)


def weather_edge(temp, wind, rain, dome):
    """One composite score per game, so the slate can be ranked and labelled.

    Most college games have no weather edge at all; saying so plainly is more
    useful than dressing up a 5 mph breeze.
    """
    if dome:
        return dict(score=0, level="indoor")
    w = max(0.0, (wind or 0) - 10) * 1.2
    r = max(0.0, (rain or 0) - 25) * 0.14
    c = max(0.0, 45 - temp) * 0.45 if temp is not None else 0.0
    h = max(0.0, temp - 88) * 0.5 if temp is not None else 0.0
    score = round(w + r + c + h, 1)
    level = ("severe" if score >= 14 else "elevated" if score >= 8
             else "watch" if score >= 3 else "none")
    return dict(score=score, level=level)


def _vals(rows, key):
    if key == "pts":
        # era-normalized points when the history carries them, raw otherwise
        return [r.get("epts", r["pts"]) for r in rows if r.get("epts", r.get("pts")) is not None]
    return [r[key] for r in rows if r.get(key) is not None]


def metric_block(rows, hist_avg, league, dome):
    """Each metric vs both baselines, or an honest blank when the sample is thin."""
    out = []
    for key, label, nd in METRICS:
        vals = _vals(rows, key)
        n = len(vals)
        cur = round(statistics.mean(vals), nd) if n else None
        lg = league.get(key)
        vn = (hist_avg or {}).get(key)
        def pct(base):
            if dome or cur is None or not base or n < MIN_METRIC_N:
                return None
            return round((cur - base) / base * 100)
        out.append(dict(k=key, label=label, n=n, cur=cur,
                        lgAvg=lg, vnAvg=vn,
                        lgPct=pct(lg), vnPct=pct(vn)))
    return out


def match_games(hist_games, temp, wind, dome):
    if dome:
        return hist_games, "indoor games (domed venue)"
    for dt, dw in ((6, 4), (8, 6), (12, 8), (15, 99)):
        rows = [g for g in hist_games
                if abs(g["t"] - temp) <= dt and abs(g["w"] - wind) <= dw]
        if len(rows) >= 10:
            note = f"±{dt}° temp, ±{dw} mph wind" if dw < 99 else f"±{dt}° temp (widened)"
            return rows, note
    return rows, "small sample — widest window"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()

    hist_all = json.load(open(HISTORY)) if os.path.exists(HISTORY) else None
    if not hist_all:
        sys.exit("data/cfb/venues_history.json missing — run the CFB history workflow first.")
    league = hist_all["_league"]

    upcoming, yr = ([], season_year(datetime.now(ET))) if args.offline else load_upcoming()
    sts = sorted({g["_season_type"] for g in upcoming}) or ["regular"]
    totals = {} if args.offline else fetch_totals(yr, sts)

    games, skipped = [], 0
    for g in upcoming:
        home, away = gv(g, "homeTeam", "home_team"), gv(g, "awayTeam", "away_team")
        vid = gv(g, "venueId", "venue_id")
        if not home or not away or not vid:
            skipped += 1
            continue
        hist = hist_all.get(str(vid))
        meta = venue_meta(vid)
        if not meta or gv(meta, "latitude") is None:
            skipped += 1
            continue
        lat, lon = meta["latitude"], meta["longitude"]
        tz = gv(meta, "timezone") or "America/New_York"
        dome = bool(gv(meta, "dome"))
        vname = gv(meta, "name") or "?"
        hconf = gv(g, "homeConference", "home_conference")
        aconf = gv(g, "awayConference", "away_conference")
        conf = hconf if hconf in P4 else (aconf if aconf in P4 else "Other")
        utc = g["_utc"]
        local = utc.astimezone(ZoneInfo(tz))
        et_dt = utc.astimezone(ET)
        tbd = bool(gv(g, "startTimeTBD", "start_time_tbd"))

        fc = forecast(lat, lon)
        h = fc["hourly"]
        want = utc.strftime("%Y-%m-%dT%H")
        idx = next((i for i, t in enumerate(h["time"]) if t.startswith(want)), None)
        if idx is None:
            skipped += 1
            continue
        temp = round(h["temperature_2m"][idx]); dew = round(h["dew_point_2m"][idx])
        wind = round(h["wind_speed_10m"][idx])
        wdir = h.get("wind_direction_10m", [None] * len(h["time"]))[idx]
        cloud = h["cloud_cover"][idx]; pp = h["precipitation_probability"][idx]
        rh = h["relative_humidity_2m"][idx]; pres = h["surface_pressure"][idx]
        icon, sky = ("🏟️", "Indoor") if dome else sky_of(cloud, pp, local.hour)

        hourly = []
        if not dome:
            for off in range(-1, 4):
                j = idx + off
                if j < 0 or j >= len(h["time"]):
                    continue
                hh = datetime.fromisoformat(h["time"][j] + ":00+00:00" if len(h["time"][j]) == 13 else h["time"][j]).replace(tzinfo=timezone.utc)
                loc_h = hh.astimezone(ZoneInfo(tz))
                ic, _ = sky_of(h["cloud_cover"][j], h["precipitation_probability"][j], loc_h.hour)
                hourly.append(dict(
                    lab=loc_h.strftime("%-I %p"), fp=(off == 0), c=ic,
                    t=round(h["temperature_2m"][j]), w=round(h["wind_speed_10m"][j]),
                    rain=None if h["precipitation_probability"][j] is None else round(h["precipitation_probability"][j]),
                    rh=None if h["relative_humidity_2m"][j] is None else round(h["relative_humidity_2m"][j])))
        delay = None
        if not dome and hourly:
            worst = max((x["rain"] or 0) for x in hourly)
            delay = dict(level=("clear" if worst < 20 else "watch" if worst < 45
                                else "likely" if worst < 70 else "severe"), pct=worst)

        today_line = totals.get(g["id"])
        badges = []
        tl = team_locations(yr).get(away)
        if tl:
            try:
                d_mi = miles(tl[0], tl[1], lat, lon)
                if d_mi >= 1200:
                    badges.append(dict(k="LONG HAUL",
                                       txt=f"{away} travels {round(d_mi):,} miles"))
            except Exception:
                pass
        ef = elev_feet(gv(meta, "elevation"))
        if ef and ef >= 4000:
            badges.append(dict(k="ALTITUDE", txt=f"{round(ef):,} ft — thin air, tired legs"))
        base = dict(
            id=str(g["id"]), away=away, home=home, week=gv(g, "week"), conf=conf,
            p4=bool(hist), stadium=vname,
            day=et_dt.strftime("%a %b %-d"),
            time="TBD" if tbd else et_dt.strftime("%-I:%M %p ET"),
            sortTime=utc.isoformat(),
            temp=temp, dew=dew, wind=0 if dome else wind,
            windLabel="ROOF/DOME" if dome else f"{wind} mph wind",
            sky=sky, skyIcon=icon, dome=dome,
            rain=None if pp is None else round(pp),
            rh=None if rh is None else round(rh),
            pres=None if pres is None else round(pres),
            feels=None if dome else feels_like(temp, rh, wind),
            edge=weather_edge(None if dome else temp, wind, pp, dome),
            fcs=bool(g.get("_fcs")),
            hourly=hourly or None, delay=delay, total=today_line,
            badges=badges or None,
            windDir=None if (dome or wdir is None) else round(wdir),
            kickHour=local.hour,
            awayLogo=(team_info(yr).get(away) or {}).get("logo"),
            homeLogo=(team_info(yr).get(home) or {}).get("logo"),
            awayColor=(team_info(yr).get(away) or {}).get("color"),
            homeColor=(team_info(yr).get(home) or {}).get("color"),
            awayAb=(team_info(yr).get(away) or {}).get("ab") or away[:4].upper(),
            homeAb=(team_info(yr).get(home) or {}).get("ab") or home[:4].upper())

        if hist:
            rows, note = match_games(hist["games"], temp, wind, dome)
            n = len(rows)
            pts_vals = _vals(rows, "pts")
            m_pts = statistics.mean(pts_vals) if pts_vals else 0
            avg_pts = hist["avg"].get("pts") or league.get("pts")
            lined = [x for x in rows if x.get("res")]
            overs = sum(1 for x in lined if x["res"] == "over")
            unders = sum(1 for x in lined if x["res"] == "under")
            base.update(
                sample=n,
                # None, not 0: below MIN_METRIC_N a headline % reads as a signal
                # when it is really just noise. The page renders None as "PTS —".
                pts=(round((m_pts - avg_pts) / avg_pts * 100)
                     if avg_pts and n >= MIN_METRIC_N and not dome else
                     (0 if dome else None)),
                ptsGm=(round(m_pts, 1) if n else None), ptsStad=avg_pts,
                metrics=metric_block(rows, hist.get("avg"), league, dome),
                venueN=hist["avg"].get("n", 0),
                ou=dict(over=round(overs / len(lined) * 100) if lined else 0,
                        under=round(unders / len(lined) * 100) if lined else 0,
                        push=round((len(lined) - overs - unders) / len(lined) * 100) if lined else 0,
                        n=len(lined)),
                note=note, windFx=None if dome else wind_receptivity(hist["games"]),
                matches=[dict(d=x["d"], t=x["t"], w=x["w"], pts=x["pts"],
                              fg=x.get("fg"), fga=x.get("fga"),
                              line=x["line"], res=x["res"])
                         for x in sorted(rows, key=lambda x: x["d"], reverse=True)[:12]])
        else:
            base.update(sample=0, pts=None, ptsGm=0, ptsStad=0, metrics=[], venueN=0,
                        ou=dict(over=0, under=0, push=0, n=0),
                        note="forecast only — no venue history", windFx=None, matches=[])
        games.append(base)

    if skipped:
        print(f"skipped {skipped} games (no venue/coords/forecast slot)")

    parts = []
    live = [g for g in games if not g["dome"]]
    p4live = [g for g in live if g["p4"]] or live
    if live:
        cold = min(live, key=lambda g: g["temp"])
        windy = max(p4live, key=lambda g: g["wind"])
        parts.append(f"Coldest kickoff: {cold['temp']}° for {cold['away']} @ {cold['home']}.")
        if windy["wind"] >= 12:
            parts.append(f"Wind watch: {windy['wind']} mph for {windy['away']} @ "
                         f"{windy['home']} at {windy['stadium']}.")
        rain = sorted([g for g in p4live if (g.get('rain') or 0) >= 45], key=lambda x: -x['rain'])[:4]
        if rain:
            parts.append("Rain risk: " + ", ".join(f"{g['away']} @ {g['home']} ({g['rain']}%)"
                                                   for g in rain) + ".")
        else:
            parts.append("No serious rain threats on the Power 4 slate.")
    domes = sum(1 for g in games if g["dome"])
    if domes:
        parts.append(f"{domes} game{'s' if domes > 1 else ''} indoors — weather-neutral.")

    counts = {k: 0 for k in ("severe", "elevated", "watch", "none", "indoor")}
    for g in games:
        counts[(g.get("edge") or {}).get("level", "none")] += 1
    if counts["none"] and not counts["severe"] and not counts["elevated"]:
        parts.append("Most of this slate is weather-neutral.")

    payload = dict(generated=datetime.now(ET).strftime("%Y-%m-%d %H:%M ET"),
                   league=league, seasons=hist_all.get("_seasons"),
                   era=hist_all.get("_era") and True or False,
                   counts=counts,
                   brief=" ".join(parts),
                   games=sorted(games, key=lambda x: x["sortTime"]))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(payload, f, separators=(",", ":"))
    print(f"Wrote {OUT}: {len(games)} games")


if __name__ == "__main__":
    main()
