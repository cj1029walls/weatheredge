#!/usr/bin/env python3
"""Build the CFB (Power 4) venue/weather history dataset.

Sources:
  - CollegeFootballData.com API (free key, CFBD_API_KEY secret):
    venues (lat/lon/dome/timezone), games 2019-2025 with final scores,
    and betting lines (median over/under across providers).
  - Open-Meteo hourly archive joined at kickoff, venue-local time.

Scope: home venues of current Power 4 teams (SEC, Big Ten, Big 12, ACC —
plus Notre Dame). History = every completed FBS game played AT those venues,
whoever was visiting.

Output: data/cfb/venues_history.json
  { "<venueId>": { "name", "team", "conf", "dome", "tz",
                   "games": [ {d, t, w, wd, pts, line, res}, ... ],
                   "avg": {pts, n} },
    "_league": {pts, n}, "_built": "...", "_seasons": [..] }

Game fields: d=YYYYMMDD, t=temp°F, w=wind mph, wd=wind direction deg
(kept raw — field bearings can be layered in later), pts=total points,
line=closing total (median across books), res=over/under/push vs that line.

No third-party dependencies.
"""
import functools, json, os, statistics, sys, time, urllib.request
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

print = functools.partial(print, flush=True)

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
OUT = os.path.join(ROOT, "data", "cfb", "venues_history.json")

CFBD = "https://api.collegefootballdata.com"
ARCHIVE_URL = ("https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lon}"
               "&start_date={start}&end_date={end}"
               "&hourly=temperature_2m,wind_speed_10m,wind_direction_10m"
               "&temperature_unit=fahrenheit&wind_speed_unit=mph&timezone=UTC")

FIRST_SEASON = 2019
LAST_SEASON = 2025
P4 = {"SEC", "Big Ten", "Big 12", "ACC"}


def gv(d, *names):
    """Get the first present key — CFBD has shipped both camelCase and snake_case."""
    for n in names:
        if n in d and d[n] is not None:
            return d[n]
    return None


def fetch(url, tries=4, timeout=60, auth=False):
    hdrs = {"User-Agent": "dfsradar-build/1.0", "Accept": "application/json"}
    if auth:
        key = os.environ.get("CFBD_API_KEY")
        if not key:
            raise SystemExit("CFBD_API_KEY not set")
        hdrs["Authorization"] = f"Bearer {key}"
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except Exception as e:
            code = getattr(e, "code", None)
            if i == tries - 1:
                raise
            wait = 45 if code == 429 else 8 * (i + 1)
            print(f"    retry {i+1}/{tries} in {wait}s: {e}")
            time.sleep(wait)


def load_p4_venues():
    """Current P4 teams and their home venues, from the most recent season."""
    games = fetch(f"{CFBD}/games?year={LAST_SEASON}&seasonType=regular", auth=True)
    print(f"cfbd: {len(games)} games in {LAST_SEASON}")
    team_conf, team_venues = {}, {}
    for g in games:
        home, conf = gv(g, "homeTeam", "home_team"), gv(g, "homeConference", "home_conference")
        vid = gv(g, "venueId", "venue_id")
        neutral = gv(g, "neutralSite", "neutral_site") or False
        if not home or conf not in P4 or neutral or not vid:
            continue
        team_conf[home] = conf
        team_venues.setdefault(home, []).append(vid)
    venues_meta = {v["id"]: v for v in fetch(f"{CFBD}/venues", auth=True)}
    out = {}
    for team in team_venues:
        vid = max(set(team_venues[team]), key=team_venues[team].count)
        meta = venues_meta.get(vid)
        if not meta:
            continue
        lat, lon = gv(meta, "latitude"), gv(meta, "longitude")
        tz = gv(meta, "timezone") or "America/New_York"
        if lat is None or lon is None:
            print(f"  skip {team}: venue {vid} has no coordinates")
            continue
        out[vid] = dict(name=gv(meta, "name") or "?", team=team, conf=team_conf[team],
                        dome=bool(gv(meta, "dome")), lat=lat, lon=lon, tz=tz)
    print(f"P4 home venues resolved: {len(out)} (teams: {len(team_conf)})")
    if not (55 <= len(out) <= 75):
        raise SystemExit(f"SANITY FAIL: {len(out)} P4 venues — conference names or API shape changed")
    return out


def load_games_and_lines(venue_ids):
    """All completed FBS games at those venues, with median closing total."""
    kept, lines = [], {}
    for yr in range(FIRST_SEASON, LAST_SEASON + 1):
        for st in ("regular", "postseason"):
            games = fetch(f"{CFBD}/games?year={yr}&seasonType={st}", auth=True)
            n0 = len(kept)
            for g in games:
                vid = gv(g, "venueId", "venue_id")
                hp, ap = gv(g, "homePoints", "home_points"), gv(g, "awayPoints", "away_points")
                start = gv(g, "startDate", "start_date")
                if vid not in venue_ids or hp is None or ap is None or not start:
                    continue
                kept.append(dict(id=g["id"], vid=vid, start=start, pts=int(hp) + int(ap)))
            print(f"  {yr} {st}: +{len(kept)-n0} games at P4 venues")
            ln = fetch(f"{CFBD}/lines?year={yr}&seasonType={st}", auth=True)
            for rec in ln:
                gid = gv(rec, "id", "gameId", "game_id")
                ous = [gv(l, "overUnder", "over_under") for l in rec.get("lines", [])]
                ous = [float(x) for x in ous if x is not None]
                if gid and ous:
                    lines[gid] = statistics.median(ous)
            time.sleep(0.6)
    print(f"total: {len(kept)} games, lines for {len(lines)}")
    if not (2200 < len(kept) < 6500):
        raise SystemExit(f"SANITY FAIL: {len(kept)} games — filters or API shape changed")
    return kept, lines


def venue_weather(meta, years):
    out = {}
    for i in range(0, len(years), 4):
        chunk = years[i:i + 4]
        end = f"{chunk[-1]}-12-31"
        if chunk[-1] >= date.today().year:
            end = (date.today() - timedelta(days=3)).isoformat()
        url = ARCHIVE_URL.format(lat=meta["lat"], lon=meta["lon"],
                                 start=f"{chunk[0]}-08-01", end=end)
        data = fetch(url)
        h = data["hourly"]
        for t, temp, ws, wd in zip(h["time"], h["temperature_2m"],
                                   h["wind_speed_10m"], h["wind_direction_10m"]):
            out[t[:13]] = (temp, ws, wd)
        time.sleep(1.2)
    return out


def main():
    venues = load_p4_venues()
    games, lines = load_games_and_lines(set(venues))

    by_venue = {}
    for g in games:
        by_venue.setdefault(g["vid"], []).append(g)

    history, league_pts = {}, []
    for i, (vid, meta) in enumerate(sorted(venues.items(), key=lambda kv: kv[1]["team"])):
        vgames = by_venue.get(vid, [])
        years = sorted({int(g["start"][:4]) for g in vgames}) or []
        rows = []
        if years:
            wx = venue_weather(meta, years)
            tzinfo = ZoneInfo(meta["tz"])
            for g in vgames:
                try:
                    utc = datetime.fromisoformat(g["start"].replace("Z", "+00:00"))
                except ValueError:
                    continue
                # archive keys are UTC hours; round kickoff to the hour
                key = utc.strftime("%Y-%m-%dT%H")
                w = wx.get(key)
                if not w or any(v is None for v in w):
                    continue
                temp, ws, wd = w
                local = utc.astimezone(tzinfo)
                line = lines.get(g["id"])
                res = None
                if line is not None:
                    res = ("push" if g["pts"] == line
                           else "over" if g["pts"] > line else "under")
                rows.append(dict(d=local.strftime("%Y%m%d"), t=round(temp), w=round(ws),
                                 wd=round(wd), pts=g["pts"], line=line, res=res))
                league_pts.append(g["pts"])
        avg = dict(pts=round(statistics.mean(x["pts"] for x in rows), 1),
                   n=len(rows)) if rows else dict(pts=0, n=0)
        history[str(vid)] = dict(name=meta["name"], team=meta["team"], conf=meta["conf"],
                                 dome=meta["dome"], tz=meta["tz"], games=rows, avg=avg)
        print(f"  [{i+1}/{len(venues)}] {meta['team']}: {len(rows)} games ({meta['name']})")

    history["_league"] = dict(pts=round(statistics.mean(league_pts), 1), n=len(league_pts))
    history["_built"] = date.today().isoformat()
    history["_seasons"] = [FIRST_SEASON, LAST_SEASON]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(history, f, separators=(",", ":"))
    print(f"Wrote {OUT} — league avg {history['_league']}")


if __name__ == "__main__":
    main()
