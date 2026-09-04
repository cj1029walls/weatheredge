#!/usr/bin/env python3
"""Build the CFB (Power 4) venue/weather history dataset.

Sources:
  - CollegeFootballData.com API (free key, CFBD_API_KEY secret):
    venues (lat/lon/dome/timezone), games 2010-2025 with final scores,
    team box stats (/games/teams), and betting lines (median over/under).
  - Open-Meteo hourly archive joined at kickoff, venue-local time.

Scope: home venues of current Power 4 teams (SEC, Big Ten, Big 12, ACC —
plus Notre Dame). History = every completed FBS game played AT those venues,
whoever was visiting.

Output: data/cfb/venues_history.json
  { "<venueId>": { "name", "team", "conf", "dome", "tz",
                   "games": [ {d, t, w, wd, pts, epts, line, res,
                               pa, ru, cp, fg, fga, fl, to}, ... ],
                   "avg": {pts, pa, ru, cp, fg, fl, to, n} },
    "_league": {pts, pa, ru, cp, fg, fl, to, n},
    "_era": {"<season>": factor}, "_built": "...", "_seasons": [..] }

Game fields: d=YYYYMMDD, t=temp°F, w=wind mph, wd=wind direction deg
(kept raw — field bearings can be layered in later), pts=total points,
epts=era-normalized total points, line=closing total (median across books),
res=over/under/push vs that line.

Box-score fields (both teams combined, None when CFBD had no box for a game):
  pa=passing yards, ru=rushing yards, cp=completion % (game-wide),
  fg=field goals made, fga=field goals attempted, fl=fumbles lost,
  to=turnovers.

ERA NORMALIZATION: college scoring in 2010 is not college scoring in 2025.
Reaching back for sample only helps if we take the era out first, so each
game carries `epts` = pts * (reference season scoring / that season's
scoring). Impact percentages are computed off `epts`; the O/U record needs
no adjustment because every game is already graded against its own closing
total.

The box-score join is FAIL-SOFT: a game with no box score is still kept with
its points, so a CFBD gap can never shrink the dataset.

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

FIRST_SEASON = 2010
LAST_SEASON = 2025      # complete seasons only — an in-progress season has too
                        # few games to derive a trustworthy era factor from
ERA_REF = 2025          # normalize every season's scoring to this one
MAX_WEEK = 17           # regular-season weeks to sweep for box scores
P4 = {"SEC", "Big Ten", "Big 12", "ACC"}

# metrics carried per game (key -> label used only in logs)
METRICS = ("pa", "ru", "cp", "fg", "fl", "to")


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
            # A 4xx that isn't rate limiting means the resource doesn't exist
            # (week 0 before it was a thing, say) — retrying just burns minutes.
            if i == tries - 1 or (code and 400 <= code < 500 and code != 429):
                raise
            wait = 45 if code == 429 else 8 * (i + 1)
            print(f"    retry {i+1}/{tries} in {wait}s: {e}")
            time.sleep(wait)


def _venue_season():
    """The season whose conference alignment we should label venues with.

    History stops at the last COMPLETE season, but conference membership keeps
    moving, so venues and conf labels come from the season being played now —
    falling back to LAST_SEASON if that schedule isn't published yet.
    """
    now = datetime.now(timezone.utc)
    cur = now.year if now.month >= 2 else now.year - 1
    if cur <= LAST_SEASON:
        return cur, None
    try:
        games = fetch(f"{CFBD}/games?year={cur}&seasonType=regular", auth=True)
    except Exception as e:
        print(f"  {cur} schedule unavailable ({e}) — labeling venues from {LAST_SEASON}")
        return LAST_SEASON, None
    if len(games or []) < 300:
        print(f"  {cur} schedule only has {len(games or [])} games — "
              f"labeling venues from {LAST_SEASON}")
        return LAST_SEASON, None
    return cur, games


def load_p4_venues():
    """Current P4 teams and their home venues, from the season being played."""
    yr, games = _venue_season()
    if games is None:
        games = fetch(f"{CFBD}/games?year={yr}&seasonType=regular", auth=True)
    print(f"cfbd: {len(games)} games in {yr} (venue/conference reference season)")
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
    return out, yr


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _pair(v):
    """CFBD ships made/attempt pairs as '22-35' (and occasionally '22/35')."""
    if v is None:
        return (None, None)
    s = str(v).replace("/", "-")
    parts = s.split("-")
    if len(parts) != 2:
        return (None, None)
    a, b = _num(parts[0]), _num(parts[1])
    return (a, b)


def _stats_of(team_entry):
    """Flatten one team's CFBD box-score stat list into {name: value}."""
    out = {}
    for s in team_entry.get("stats") or []:
        cat = gv(s, "category")
        if cat is not None:
            out[cat] = gv(s, "stat")
    return out


def load_box_stats(seasons):
    """Game-level box totals (both teams combined), keyed by CFBD game id.

    Swept by year+week because /games/teams needs a week, team or conference.
    Any week that errors is skipped — the join is fail-soft by design.
    """
    box, calls, missing_weeks = {}, 0, 0
    for yr in seasons:
        got_year = 0
        for st, weeks in (("regular", range(0, MAX_WEEK + 1)), ("postseason", [1])):
            for wk in weeks:
                url = f"{CFBD}/games/teams?year={yr}&seasonType={st}&week={wk}"
                try:
                    recs = fetch(url, tries=3, auth=True)
                    calls += 1
                except Exception as e:
                    missing_weeks += 1
                    print(f"    {yr} {st} wk{wk}: box unavailable ({e})")
                    continue
                for rec in recs or []:
                    gid = gv(rec, "id", "gameId", "game_id")
                    teams = rec.get("teams") or []
                    if gid is None or len(teams) != 2:
                        continue
                    pa = ru = fl = to = 0.0
                    fgm = fga = 0.0
                    comp = att = 0.0
                    seen_pa = seen_ru = seen_fg = seen_cmp = seen_fl = seen_to = False
                    for t in teams:
                        s = _stats_of(t)
                        v = _num(gv(s, "netPassingYards", "passingYards"))
                        if v is not None:
                            pa += v; seen_pa = True
                        v = _num(s.get("rushingYards"))
                        if v is not None:
                            ru += v; seen_ru = True
                        c, a = _pair(s.get("completionAttempts"))
                        if c is None:
                            c, a = _num(s.get("passCompletions")), _num(s.get("passAttempts"))
                        if c is not None and a:
                            comp += c; att += a; seen_cmp = True
                        m, at = _pair(s.get("fieldGoals"))
                        if m is not None:
                            fgm += m; fga += (at or 0); seen_fg = True
                        v = _num(s.get("fumblesLost"))
                        if v is not None:
                            fl += v; seen_fl = True
                        v = _num(s.get("turnovers"))
                        if v is not None:
                            to += v; seen_to = True
                    box[gid] = dict(
                        pa=round(pa) if seen_pa else None,
                        ru=round(ru) if seen_ru else None,
                        cp=round(comp / att * 100, 1) if (seen_cmp and att) else None,
                        fg=round(fgm, 1) if seen_fg else None,
                        fga=round(fga, 1) if seen_fg else None,
                        fl=round(fl, 1) if seen_fl else None,
                        to=round(to, 1) if seen_to else None)
                    got_year += 1
                time.sleep(0.5)
        print(f"  box {yr}: {got_year} games")
    print(f"box scores: {len(box)} games over {calls} calls"
          + (f" ({missing_weeks} weeks unavailable)" if missing_weeks else ""))
    return box


def load_games_and_lines(venue_ids, seasons):
    """All completed FBS games at those venues, with median closing total."""
    kept, lines = [], {}
    for yr in seasons:
        for st in ("regular", "postseason"):
            games = fetch(f"{CFBD}/games?year={yr}&seasonType={st}", auth=True)
            n0 = len(kept)
            for g in games:
                vid = gv(g, "venueId", "venue_id")
                hp, ap = gv(g, "homePoints", "home_points"), gv(g, "awayPoints", "away_points")
                start = gv(g, "startDate", "start_date")
                if vid not in venue_ids or hp is None or ap is None or not start:
                    continue
                kept.append(dict(id=g["id"], vid=vid, start=start, season=yr,
                                 pts=int(hp) + int(ap)))
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
    lo, hi = 800 * len(seasons) // 7, 1400 * len(seasons)
    if not (lo < len(kept) < hi):
        raise SystemExit(f"SANITY FAIL: {len(kept)} games over {len(seasons)} seasons "
                         f"(expected {lo}-{hi}) — filters or API shape changed")
    return kept, lines


def era_factors(games):
    """Per-season scoring factor that maps a season onto ERA_REF's environment."""
    by_season = {}
    for g in games:
        by_season.setdefault(g["season"], []).append(g["pts"])
    means = {s: statistics.mean(v) for s, v in by_season.items() if v}
    ref = means.get(ERA_REF) or (statistics.mean(means.values()) if means else 0)
    if not ref:
        return {}, means
    out = {}
    for s, m in sorted(means.items()):
        f = round(ref / m, 4) if m else 1.0
        out[str(s)] = f
        print(f"  era {s}: {m:.1f} pts/gm -> x{f}")
    return out, means


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


def _mean_of(rows, key, nd=1):
    vals = [r[key] for r in rows if r.get(key) is not None]
    return round(statistics.mean(vals), nd) if vals else None


def main():
    seasons = list(range(FIRST_SEASON, LAST_SEASON + 1))
    venues, venue_yr = load_p4_venues()
    games, lines = load_games_and_lines(set(venues), seasons)
    era, season_means = era_factors(games)
    box = load_box_stats(seasons)
    matched_box = sum(1 for g in games if g["id"] in box)
    print(f"box join: {matched_box}/{len(games)} games carry box stats "
          f"({round(matched_box/len(games)*100)}%)")

    by_venue = {}
    for g in games:
        by_venue.setdefault(g["vid"], []).append(g)

    history, league_rows = {}, []
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
                f = era.get(str(g["season"]), 1.0)
                row = dict(d=local.strftime("%Y%m%d"), t=round(temp), w=round(ws),
                           wd=round(wd), pts=g["pts"], epts=round(g["pts"] * f, 1),
                           line=line, res=res)
                row.update(box.get(g["id"]) or
                           {k: None for k in ("pa", "ru", "cp", "fg", "fga", "fl", "to")})
                rows.append(row)
                league_rows.append(row)
        avg = dict(n=len(rows))
        if rows:
            avg["pts"] = round(statistics.mean(x["epts"] for x in rows), 1)
            for k in METRICS:
                avg[k] = _mean_of(rows, k)
        else:
            avg["pts"] = 0
            for k in METRICS:
                avg[k] = None
        history[str(vid)] = dict(name=meta["name"], team=meta["team"], conf=meta["conf"],
                                 dome=meta["dome"], tz=meta["tz"], games=rows, avg=avg)
        print(f"  [{i+1}/{len(venues)}] {meta['team']}: {len(rows)} games ({meta['name']})")

    lg = dict(n=len(league_rows),
              pts=round(statistics.mean(x["epts"] for x in league_rows), 1) if league_rows else 0)
    for k in METRICS:
        lg[k] = _mean_of(league_rows, k)
    history["_league"] = lg
    history["_era"] = era
    history["_built"] = date.today().isoformat()
    history["_seasons"] = [FIRST_SEASON, LAST_SEASON]
    history["_confSeason"] = venue_yr
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(history, f, separators=(",", ":"))
    size = os.path.getsize(OUT)
    print(f"Wrote {OUT} ({size/1e6:.1f} MB) — league {lg}")


if __name__ == "__main__":
    main()
