#!/usr/bin/env python3
"""CollegeFootballData (CFBD) client with a committed, per-endpoint TTL cache.

Why this exists. The free CFBD plan is 1,000 calls a month, shared by every CFB
script. The weekly workflow re-downloaded season-static data (venues, FBS team
list, last season's stats, rosters) on every run -- ~12 calls a run, ~35 runs a
month -- and on a 429 it retried 4-5 times with 45-second sleeps, each retry
another counted call, before crashing. In September 2026 that plus two in-season
history rebuilds (~370 calls each) exhausted the quota on Sept 20; the key has
been disabled since, and the pages kept last week's data without saying so.

Rules:
  * Responses live in data/cfb/cache/ (the workflow commits the folder, so a
    fresh runner starts warm). Payloads are trimmed to the fields the builders
    read, rows sorted, one row per line: small files, small git diffs, and a
    file is rewritten only when its content actually changed.
  * A cached copy younger than its TTL is returned without a call (see TTL).
  * An expired copy is refreshed; if CFBD fails (429, 401/403, 5xx, timeout,
    bad JSON) the old copy is returned instead and recorded as stale, with a
    human reason. Builders put status() / stale_note() into their JSON so the
    page can say what is not fresh.
  * 429 / 401 / 403 are never retried: a monthly quota does not come back in
    45 seconds. CFBD is then treated as down for DOWN_FOR (persisted in the
    index, so the other scripts in the same job make zero calls too). 5xx and
    network errors get exactly one retry.
  * X-CallLimit-Remaining, when CFBD sends it, is logged and kept in the index.
    Below CFBD_MIN_REMAINING an endpoint that has any cached copy is served
    from cache rather than spending one of the last calls of the month.
  * Two network failures in one process and the rest of that run is served
    from cache (a hard outage costs ~2 minutes, not 60 s x every endpoint).
  * A response that shrinks a core list (games, venues, teams, roster) to under
    half its cached size is treated as an API glitch: the cached copy is kept.

Env: CFBD_API_KEY, CFBD_CACHE_DIR (default data/cfb/cache), CFBD_MIN_REMAINING.
No third-party dependencies.
"""
import hashlib, json, os, re, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

BASE = "https://api.collegefootballdata.com"
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CACHE_DIR = os.environ.get("CFBD_CACHE_DIR") or os.path.join(ROOT, "data", "cfb", "cache")
INDEX = os.path.join(CACHE_DIR, "_index.json")
ET = ZoneInfo("America/New_York")
HOUR, DAY = 3600, 86400
AUTO = object()           # "use the endpoint's default TTL"
FOREVER = None            # finished seasons never change
DOWN_FOR = 6 * HOUR       # after a 429/401/403, no calls until this has passed
MIN_REMAINING = int(os.environ.get("CFBD_MIN_REMAINING", "40"))
SHRINK_GUARD = {"/games", "/venues", "/teams/fbs", "/roster"}

# Default freshness per endpoint for the CURRENT season (a past season's data
# is final and cached forever). Games and lines are refreshed once per run and
# shared by weekly_build.py and cfb_build.py, which run minutes apart.
TTL = {
    "/venues": 30 * DAY,
    "/teams/fbs": 14 * DAY,
    "/roster": 7 * DAY,
    "/stats/season": DAY,
    "/stats/player/season": DAY,
    "/games": 6 * HOUR,
    "/lines": 6 * HOUR,
    "/games/teams": 3 * DAY,
}


class Unavailable(RuntimeError):
    """Neither a fresh response nor any cached copy is available.
    `.why` is the short, page-safe reason (no URLs)."""
    def __init__(self, why, label=""):
        super().__init__(f"{why}; no cached copy of {label}" if label else why)
        self.why = why


class _Refused(Exception):
    """CFBD answered 401/403/429: do not retry, do not call again for a while."""


_IDX = None
_STATS = {"calls": 0, "hits": 0, "stale": 0, "netfail": 0}
_DEGRADED = []            # [{endpoint, reason, asOf}] for this process


def season_now(now=None):
    now = now or datetime.now(ET)
    return now.year if now.month >= 2 else now.year - 1


# ---------------------------------------------------------------- trimming
def _keep(row, keys):
    return {k: row[k] for k in keys if k in row}


def _snake(*names):
    """camelCase names plus the snake_case spellings CFBD v1 used."""
    out = []
    for n in names:
        out.append(n)
        s = re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", n).lower()   # startTimeTBD -> start_time_tbd
        if s != n:
            out.append(s)
    return tuple(out)


GAME_KEYS = _snake("id", "season", "week", "seasonType", "startDate", "startTimeTBD",
                   "completed", "neutralSite", "venueId", "venue",
                   "homeTeam", "homeConference", "homeClassification", "homePoints",
                   "awayTeam", "awayConference", "awayClassification", "awayPoints") + (
                   "home_division", "away_division")
TRENCH_POS = {"OL", "OT", "OG", "C", "G", "T", "DL", "DT", "DE", "NT", "EDGE",
              "RB", "FB", "HB", "TB"}
BOX_STATS = {"rushingAttempts", "rushingYards", "netPassingYards", "passingYards",
             "completionAttempts", "passCompletions", "passAttempts", "fieldGoals",
             "fumblesLost", "turnovers"}


def _cls(g, *names):
    for n in names:
        if g.get(n):
            return str(g[n]).lower()
    return ""


def _trim_games(rows):
    # Only games with an FBS side are ever read (free slate: either side FBS;
    # PRO board: both). Everything else is ~75% of the payload.
    keep = [_keep(g, GAME_KEYS) for g in rows
            if "fbs" in (_cls(g, "homeClassification", "home_division"),
                         _cls(g, "awayClassification", "away_division"))]
    return sorted(keep, key=lambda g: g.get("id") or 0)


def _trim_lines(rows):
    out = []
    for r in rows:
        x = _keep(r, _snake("id", "gameId", "season", "seasonType", "week",
                            "startDate", "homeTeam", "awayTeam"))
        x["lines"] = [_keep(l, _snake("provider", "spread", "overUnder"))
                      for l in (r.get("lines") or [])]
        out.append(x)
    return sorted(out, key=lambda r: r.get("id") or r.get("gameId") or 0)


def _trim_venues(rows):
    keys = _snake("id", "name", "latitude", "longitude", "timezone", "dome", "elevation",
                  "city", "state", "location")
    return sorted((_keep(v, keys) for v in rows), key=lambda v: v.get("id") or 0)


def _trim_teams(rows):
    keys = _snake("id", "school", "abbreviation", "color", "alternateColor", "logos",
                  "conference", "classification", "location")
    out = []
    for t in rows:
        x = _keep(t, keys)
        loc = x.get("location")
        if isinstance(loc, dict):
            x["location"] = _keep(loc, _snake("latitude", "longitude", "venueId", "name"))
        out.append(x)
    return sorted(out, key=lambda t: str(t.get("school")))


def _trim_roster(rows):
    # The PRO board reads OL/DL weights and running-back names only; the other
    # positions are ~55% of a 20k-row payload. Widen TRENCH_POS if that changes.
    keys = _snake("id", "team", "firstName", "lastName", "position", "weight")
    keep = [_keep(p, keys) for p in rows
            if str(p.get("position") or "").upper() in TRENCH_POS]
    return sorted(keep, key=lambda p: (str(p.get("team")), str(p.get("id"))))


def _trim_season_stats(rows):
    want = {"rushingAttempts", "passAttempts", "games"}
    keys = _snake("team", "conference", "statName", "statValue")
    keep = [_keep(r, keys) for r in rows
            if (r.get("statName") or r.get("stat_name")) in want]
    return sorted(keep, key=lambda r: (str(r.get("team")), str(r.get("statName") or r.get("stat_name"))))


def _trim_player_stats(rows):
    keys = _snake("playerId", "player", "position", "team", "category", "statType", "stat")
    keep = [_keep(r, keys) for r in rows
            if str(r.get("statType") or r.get("stat_type") or "").upper() in ("YDS", "CAR")]
    return sorted(keep, key=lambda r: (str(r.get("team")), str(r.get("player")),
                                       str(r.get("statType") or r.get("stat_type"))))


def _trim_box(rows):
    out = []
    for g in rows:
        x = _keep(g, _snake("id", "gameId"))
        x["teams"] = []
        for t in g.get("teams") or []:
            y = _keep(t, _snake("teamId", "school", "team", "homeAway", "points"))
            y["stats"] = [s for s in (t.get("stats") or []) if s.get("category") in BOX_STATS]
            x["teams"].append(y)
        out.append(x)
    return sorted(out, key=lambda g: g.get("id") or 0)


TRIM = {
    "/games": _trim_games, "/lines": _trim_lines, "/venues": _trim_venues,
    "/teams/fbs": _trim_teams, "/roster": _trim_roster,
    "/stats/season": _trim_season_stats, "/stats/player/season": _trim_player_stats,
    "/games/teams": _trim_box,
}


# ---------------------------------------------------------------- storage
def _key(path, params):
    parts = [path.strip("/").replace("/", "_")]
    parts += [f"{k}-{params[k]}" for k in sorted(params)]
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in "__".join(parts))


def _label(path, params):
    q = urllib.parse.urlencode(sorted(params.items()))
    return path + (f"?{q}" if q else "")


def _index():
    global _IDX
    if _IDX is None:
        try:
            with open(INDEX) as f:
                _IDX = json.load(f)
        except Exception:
            _IDX = {}
        _IDX.setdefault("_meta", {})
    return _IDX


def _save_index():
    os.makedirs(CACHE_DIR, exist_ok=True)
    tmp = INDEX + ".tmp"
    with open(tmp, "w") as f:
        json.dump(_index(), f, indent=1, sort_keys=True)
        f.write("\n")
    os.replace(tmp, INDEX)


def _dumps(data):
    if isinstance(data, list):
        rows = [json.dumps(r, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                for r in data]
        return "[\n" + ",\n".join(rows) + "\n]\n" if rows else "[]\n"
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"


def _read(key):
    try:
        with open(os.path.join(CACHE_DIR, key + ".json"), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _store(key, path, params, data, ttl):
    text = _dumps(data)
    sha = hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
    idx = _index()
    fp = os.path.join(CACHE_DIR, key + ".json")
    if idx.get(key, {}).get("sha") != sha or not os.path.exists(fp):
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(fp + ".tmp", "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(fp + ".tmp", fp)
    now = time.time()
    idx[key] = dict(endpoint=_label(path, params), t=int(now), at=_iso(now),
                    ttl=ttl, rows=(len(data) if isinstance(data, list) else None),
                    bytes=len(text), sha=sha)
    _save_index()


def _iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _et(ts):
    return datetime.fromtimestamp(ts, ET).strftime("%a %b %-d %-I:%M %p ET")


# ---------------------------------------------------------------- network
def _note_remaining(v):
    try:
        n = int(v)
    except (TypeError, ValueError):
        return
    _STATS["remaining"] = n
    _index()["_meta"]["remaining"] = dict(n=n, at=_iso(time.time()), t=int(time.time()))


def _fetch(path, params):
    url = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={
        "User-Agent": "dfsradar-build/1.0", "Accept": "application/json",
        "Authorization": f"Bearer {os.environ.get('CFBD_API_KEY', '')}"})
    for attempt in (1, 2):
        _STATS["calls"] += 1
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                _note_remaining(r.headers.get("X-CallLimit-Remaining"))
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            _note_remaining(e.headers.get("X-CallLimit-Remaining") if e.headers else None)
            if e.code == 429:
                raise _Refused("CollegeFootballData refused the call (HTTP 429 — "
                               "monthly call quota exhausted or rate-limited)")
            if e.code in (401, 403):
                raise _Refused(f"CollegeFootballData rejected the API key (HTTP {e.code})")
            if e.code < 500 or attempt == 2:
                raise
        except Exception:
            if attempt == 2:
                raise
        time.sleep(5)


def _blocked():
    """Why the network must not be used right now, or None."""
    if not os.environ.get("CFBD_API_KEY"):
        return "no CFBD_API_KEY configured"
    if _STATS["netfail"] >= 2:
        return "CollegeFootballData is not responding"
    down = _index()["_meta"].get("down")
    if down and time.time() < down.get("until", 0):
        print(f"  cfbd: marked down at {down.get('at')} — no calls before {_et(down['until'])}")
        return down.get("reason") or "CollegeFootballData unavailable"
    return None


def _budget_low():
    # Only trust a reading from the last 24 h: the quota resets, and a stale
    # "0 left" from last month must not block refreshes forever.
    rem = _index()["_meta"].get("remaining") or {}
    return (isinstance(rem.get("n"), int) and rem["n"] < MIN_REMAINING
            and time.time() - rem.get("t", 0) < DAY)


# ---------------------------------------------------------------- public API
def peek(path, **params):
    """The cached copy (any age) without touching the network, or None."""
    params = {k: v for k, v in params.items() if v is not None}
    key = _key(path, params)
    return _read(key) if key in _index() else None


def get(path, ttl=AUTO, **params):
    """Fresh-enough data for `path`, from cache or CFBD; stale cache on failure.

    Raises Unavailable when CFBD cannot be used and nothing is cached."""
    params = {k: v for k, v in params.items() if v is not None}
    key, label = _key(path, params), _label(path, params)
    if ttl is AUTO:
        year = params.get("year")
        ttl = FOREVER if (year is not None and int(year) < season_now()) else TTL.get(path, DAY)
    ent = _index().get(key)
    cached = _read(key) if ent else None
    if cached is not None and (ttl is None or time.time() - ent["t"] < ttl):
        _STATS["hits"] += 1
        print(f"  cfbd {label}: cache ({ent['at']})")
        return cached

    why = _blocked()
    if why is None and cached is not None and _budget_low():
        why = f"CFBD call budget low ({_index()['_meta']['remaining']['n']} left this month)"
    if why is None:
        why = _refresh(path, params, key, label, ttl, cached)
        if why is None:
            return _read(key)

    if cached is not None:
        _STATS["stale"] += 1
        _DEGRADED.append(dict(endpoint=label, reason=why, asOf=ent["t"]))
        print(f"  cfbd {label}: {why} — using cached copy from {_et(ent['t'])}")
        return cached
    raise Unavailable(why, label)


def _refresh(path, params, key, label, ttl, cached):
    """Fetch, trim, sanity-check and store. None on success, else the reason."""
    try:
        data = _fetch(path, params)
    except _Refused as e:
        _index()["_meta"]["down"] = dict(reason=str(e), at=_iso(time.time()),
                                         until=int(time.time() + DOWN_FOR))
        _save_index()
        return str(e)
    except Exception as e:
        _STATS["netfail"] += 1
        return f"CollegeFootballData request failed ({str(e)[:120]})"
    try:
        data = TRIM.get(path, lambda x: x)(data)
    except Exception as e:
        return f"CollegeFootballData sent an unexpected response ({type(e).__name__})"
    if (path in SHRINK_GUARD and isinstance(cached, list) and len(cached) >= 20
            and len(data) < len(cached) / 2):
        return (f"CollegeFootballData returned {len(data)} rows for {path} "
                f"(cached copy has {len(cached)}) — kept the cached copy")
    _store(key, path, params, data, ttl)
    print(f"  cfbd {label}: fetched" + (f" ({len(data)} rows)" if isinstance(data, list) else ""))
    return None


def status():
    """Status block for an output JSON, or None when everything was fresh."""
    if not _DEGRADED:
        return None
    oldest = min(d["asOf"] for d in _DEGRADED)
    return dict(ok=False, stale=True, source="CollegeFootballData",
                reason=_DEGRADED[0]["reason"], asOf=_et(oldest),
                endpoints=sorted({d["endpoint"] for d in _DEGRADED}),
                checked=datetime.now(ET).strftime("%Y-%m-%d %H:%M ET"),
                run=os.environ.get("GITHUB_RUN_ID"))


def stale_note(what="schedule & lines"):
    st = status()
    if not st:
        return None
    return f"Our college data source isn't answering — {what} as of {st['asOf']}."


def page_reason(why):
    """Reader-facing wording for a failure; the technical reason stays in
    status.reason for the logs."""
    w = (why or "").lower()
    if "429" in w or "quota" in w or "rejected" in w or "refused" in w or "down" in w \
            or "not responding" in w or "request failed" in w:
        return "our college data source isn't answering right now"
    return "our college data source sent something unexpected"


def mark_stale(path, reason, field="note"):
    """Keep the last good JSON at `path` but say, in it, that it is not fresh.

    Used when a builder cannot produce anything at all. `field` is the text the
    page already renders (free pages: "brief", PRO boards: "note"), so no page
    change is needed for readers to see it."""
    try:
        with open(path) as f:
            data = json.load(f)
    except Exception:
        data = {}
    if not isinstance(data, dict):
        return False
    prev = data.get("status") if isinstance(data.get("status"), dict) else {}
    last_good = (prev.get("lastGood") if prev.get("ok") is False else None) or \
        data.get("generated") or data.get("updated") or data.get("built")
    orig = prev.get("orig") if prev.get("ok") is False else data.get(field)
    data["stale"] = True
    data["status"] = dict(ok=False, stale=True, reason=reason, lastGood=last_good,
                          checked=datetime.now(ET).strftime("%Y-%m-%d %H:%M ET"),
                          run=os.environ.get("GITHUB_RUN_ID"), orig=orig)
    since = f" since {last_good}" if last_good else ""
    data[field] = f"⚠ Not refreshed{since} — {page_reason(reason)}." + (f" {orig}" if orig else "")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, separators=(",", ":"))
    return True


def report(tag="cfbd"):
    """One log line (+ a GitHub step-summary row and a warning when stale)."""
    rem = _STATS.get("remaining", (_index()["_meta"].get("remaining") or {}).get("n"))
    line = (f"{tag}: {_STATS['calls']} CFBD call(s), {_STATS['hits']} cache hit(s), "
            f"{_STATS['stale']} served stale; X-CallLimit-Remaining={rem if rem is not None else '?'}")
    print(line)
    if _index()["_meta"]:
        _save_index()           # persist remaining-calls reading even on all-hit runs
    summ = os.environ.get("GITHUB_STEP_SUMMARY")
    if summ:
        try:
            with open(summ, "a") as f:
                f.write(f"- {line}\n")
        except OSError:
            pass
    if _DEGRADED:
        print(f"::warning title={tag}: CFBD data served from cache::{_DEGRADED[0]['reason']} — "
              f"{len(_DEGRADED)} endpoint(s) from cache, oldest {status()['asOf']}")
