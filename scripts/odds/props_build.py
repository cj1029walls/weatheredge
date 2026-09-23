#!/usr/bin/env python3
"""Build the MLB player-props odds feed for DFSRADAR PRO.

Pulls batter home run + pitcher strikeout prop odds from The Odds API for
today's slate, aggregates a median price per player across US books, converts
to implied probabilities, and publishes site/pro/props.json (served on
dfsradar.com with CORS *, so the PRO app can fetch it directly).

Games are ranked by the radar's HR edge (fetched from dfsradar.com/data.json)
so if GAMES_CAP trims the slate, the most bettable games survive.

Env:
  ODDS_API_KEY     required
  GAMES_CAP        max games to pull props for (default 16 = full slate)
  MARKETS          comma list (default batter_home_runs,batter_home_runs_alternate,
                   pitcher_strikeouts)
  PROPS_REUSE_MIN  if props.json was refreshed less than this many minutes ago
                   (odds-props.yml lands just before daily.yml), reuse it: 0 credits

Credits: one request per event costs (markets returned x regions) -- ~3 per
game here, ~45 per full-slate refresh; the /events listing is free. Only games
not yet under way are bought: in-play lines are not pre-game prices, so a game
that has started keeps the last pre-game prices from the previous feed.

No third-party dependencies.
"""
import functools, json, os, statistics, sys, time, urllib.request
from datetime import datetime, timedelta, timezone, time as dtime

print = functools.partial(print, flush=True)

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
OUT = os.path.join(ROOT, "site", "pro", "props.json")

API = "https://api.the-odds-api.com/v4/sports/baseball_mlb"
RADAR = "https://dfsradar.com/data.json"
from zoneinfo import ZoneInfo
ET = ZoneInfo("America/New_York")  # real Eastern time: a fixed UTC-4 is an hour off from Nov 1 (DST ends)

TEAM_NAMES = {
    "Arizona Diamondbacks":"ARI","Atlanta Braves":"ATL","Baltimore Orioles":"BAL",
    "Boston Red Sox":"BOS","Chicago Cubs":"CHC","Chicago White Sox":"CWS",
    "Cincinnati Reds":"CIN","Cleveland Guardians":"CLE","Colorado Rockies":"COL",
    "Detroit Tigers":"DET","Houston Astros":"HOU","Kansas City Royals":"KC",
    "Los Angeles Angels":"LAA","Los Angeles Dodgers":"LAD","Miami Marlins":"MIA",
    "Milwaukee Brewers":"MIL","Minnesota Twins":"MIN","New York Mets":"NYM",
    "New York Yankees":"NYY","Oakland Athletics":"ATH","Athletics":"ATH",
    "Philadelphia Phillies":"PHI","Pittsburgh Pirates":"PIT","San Diego Padres":"SD",
    "San Francisco Giants":"SF","Seattle Mariners":"SEA","St. Louis Cardinals":"STL",
    "Tampa Bay Rays":"TB","Texas Rangers":"TEX","Toronto Blue Jays":"TOR",
    "Washington Nationals":"WSH",
}

REMAINING = {"v": None}


def get_json(url, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "dfsradar-pro/1.0"})
            with urllib.request.urlopen(req, timeout=45) as r:
                rem = r.headers.get("x-requests-remaining")
                if rem is not None:
                    REMAINING["v"] = rem
                return json.loads(r.read())
        except Exception as e:
            if i == tries - 1:
                raise
            print(f"    retry {i+1}/{tries}: {e}")
            time.sleep(6 * (i + 1))


def implied_pct(american):
    """American odds -> implied probability, in percent."""
    if american is None:
        return None
    a = float(american)
    p = 100.0 / (a + 100.0) if a > 0 else -a / (-a + 100.0)
    return round(p * 100, 1)


def main():
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        sys.exit("ODDS_API_KEY not set")
    cap = int(os.environ.get("GAMES_CAP", "16"))
    markets = os.environ.get("MARKETS", "batter_home_runs,batter_home_runs_alternate,pitcher_strikeouts")
    try:
        prev = json.load(open(OUT)) if os.path.exists(OUT) else None
    except Exception:
        prev = None
    reuse = int(os.environ.get("PROPS_REUSE_MIN") or 0)
    if reuse and prev and not prev.get("stale"):
        try:
            gen = datetime.strptime(prev["generated"], "%Y-%m-%d %H:%M ET").replace(tzinfo=ET)
            age = (datetime.now(ET) - gen).total_seconds() / 60
        except (KeyError, TypeError, ValueError):
            age = None
        if age is not None and 0 <= age < reuse:
            print(f"props.json refreshed {age:.0f} min ago (< {reuse}) — reusing it, 0 credits")
            return

    # today's radar slate, for edge-ranking (best-effort) — prefer the local
    # file when running inside the daily workflow (it was built moments ago)
    edge = {}
    try:
        local = os.path.join(ROOT, "site", "data.json")
        radar = json.load(open(local)) if os.path.exists(local) else get_json(RADAR)
        for g in radar.get("games", []):
            edge[f"{g['away']}@{g['home']}"] = abs(g.get("hr", 0) or 0)
    except Exception as e:
        print(f"radar data unavailable ({e}) — using schedule order")

    # events listing is free (no credit cost)
    events = get_json(f"{API}/events?apiKey={key}")
    now = datetime.now(timezone.utc)
    # Today's slate only (first pitches before 6 AM ET tomorrow): the old +26h
    # window bought tomorrow's games on every evening run.
    slate_end = datetime.combine(now.astimezone(ET).date() + timedelta(days=1),
                                 dtime(6, 0), tzinfo=ET)
    todays, started = [], []
    for ev in events:
        try:
            t = datetime.fromisoformat(ev["commence_time"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        if not (now - timedelta(hours=5) <= t <= slate_end):
            continue
        a, h = TEAM_NAMES.get(ev.get("away_team")), TEAM_NAMES.get(ev.get("home_team"))
        if not a or not h:
            continue
        rec = dict(id=ev["id"], away=a, home=h, t=t, rank=edge.get(f"{a}@{h}", 0))
        # under way: never buy in-play lines — carry the pre-game prices below
        (started if t <= now + timedelta(minutes=5) else todays).append(rec)
    todays.sort(key=lambda x: -x["rank"])
    picked = todays[:cap]
    print(f"slate: {len(todays)} games, pulling props for {len(picked)} "
          f"(markets: {markets})")

    games = []
    for ev in sorted(picked, key=lambda x: x["t"]):
        try:
            data = get_json(f"{API}/events/{ev['id']}/odds?apiKey={key}"
                            f"&regions=us&markets={markets}&oddsFormat=american")
        except Exception as e:
            print(f"  {ev['away']}@{ev['home']}: props unavailable ({e})")
            continue
        hr_prices, ks_lines, alt_prices = {}, {}, {}
        for bk in data.get("bookmakers", []):
            for mk in bk.get("markets", []):
                for oc in mk.get("outcomes", []):
                    player = oc.get("description")
                    if not player or oc.get("price") is None:
                        continue
                    if mk["key"] == "batter_home_runs" and oc.get("name") == "Over" \
                            and (oc.get("point") in (0.5, None)):
                        hr_prices.setdefault(player, []).append(oc["price"])
                    elif mk["key"] == "batter_home_runs_alternate" and oc.get("name") == "Over" \
                            and oc.get("point") == 1.5:
                        alt_prices.setdefault(player, []).append(oc["price"])
                    elif mk["key"] == "pitcher_strikeouts":
                        d = ks_lines.setdefault(player, {"points": [], "over": [], "under": []})
                        if oc.get("point") is not None:
                            d["points"].append(oc["point"])
                        if oc.get("name") == "Over":
                            d["over"].append(oc["price"])
                        elif oc.get("name") == "Under":
                            d["under"].append(oc["price"])
        hr = []
        for p, v in hr_prices.items():
            row = dict(player=p, price=round(statistics.median(v)), books=len(v),
                       implied=implied_pct(statistics.median(v)))
            av = alt_prices.get(p)
            if av:
                row["alt"] = dict(price=round(statistics.median(av)), books=len(av),
                                  implied=implied_pct(statistics.median(av)))
            hr.append(row)
        hr.sort(key=lambda x: -(x["implied"] or 0))
        ks = []
        for p, d in ks_lines.items():
            if not d["points"]:
                continue
            ks.append(dict(player=p, line=statistics.median(d["points"]),
                           over=round(statistics.median(d["over"])) if d["over"] else None,
                           under=round(statistics.median(d["under"])) if d["under"] else None,
                           impliedOver=implied_pct(statistics.median(d["over"])) if d["over"] else None))
        ks.sort(key=lambda x: -(x["impliedOver"] or 0))
        games.append(dict(id=ev["id"], away=ev["away"], home=ev["home"],
                          commence=ev["t"].astimezone(ET).strftime("%Y-%m-%d %H:%M ET"),
                          hr=hr, ks=ks))
        print(f"  {ev['away']}@{ev['home']}: {len(hr)} HR props, {len(ks)} K props")
        time.sleep(0.6)

    prev_games = {g.get("id"): g for g in (prev or {}).get("games", [])}
    kept = [dict(prev_games[ev["id"]], pregame=True) for ev in started if ev["id"] in prev_games]
    if started:
        print(f"{len(started)} game(s) under way: kept last pre-game prices for {len(kept)}, 0 credits")
    games = sorted(games + kept, key=lambda g: g.get("commence") or "")

    payload = dict(generated=datetime.now(ET).strftime("%Y-%m-%d %H:%M ET"),
                   source="The Odds API · median across US books",
                   note="Implied % straight from median Over price (vig included, "
                        "~5-7 pts on one-sided HR markets)",
                   creditsRemaining=REMAINING["v"], games=games)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(payload, f, separators=(",", ":"))
    total_hr = sum(len(g["hr"]) for g in games)
    print(f"Wrote {OUT}: {len(games)} games, {total_hr} HR props "
          f"(credits remaining: {REMAINING['v']})")


if __name__ == "__main__":
    main()
