#!/usr/bin/env python3
"""Venue Atlas -> site/atlas/data.json, one page per venue, and a sitemap.

Every ballpark, stadium, course and track we have history for, with its
weather personality in our own numbers: what the weather usually is there and
what happened in the games, rounds and races played in it. Nothing here is
fetched: it is all computed from the history files the sport builders already
keep (data/parks_history.json, data/nfl/stadiums_history.json,
data/cfb/venues_history.json, data/pga/deep.json, data/nascar/deep.json) and
the schedule/venue tables in scripts/.

Each venue also carries the `spec` the 3D engine draws it from. What the model
is, and is not, is said in `model` and shown under the drawing.

A venue page is site/atlas/index.html with its title, description and
canonical swapped and data-venue set: one template, real URLs for search.
No third-party dependencies.     python scripts/atlas/build.py
"""
import html, importlib.util, json, math, os, re, statistics, sys
from datetime import datetime

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SITE = os.path.join(ROOT, "site")
OUT = os.path.join(SITE, "atlas")
BASE = "https://dfsradar.com"
MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MIN_N = 25      # a split is only quoted with at least this many games on each side

MLB = dict(ARI="Arizona Diamondbacks", ATH="Athletics", ATL="Atlanta Braves", BAL="Baltimore Orioles",
           BOS="Boston Red Sox", CHC="Chicago Cubs", CIN="Cincinnati Reds", CLE="Cleveland Guardians",
           COL="Colorado Rockies", CWS="Chicago White Sox", DET="Detroit Tigers", HOU="Houston Astros",
           KC="Kansas City Royals", LAA="Los Angeles Angels", LAD="Los Angeles Dodgers", MIA="Miami Marlins",
           MIL="Milwaukee Brewers", MIN="Minnesota Twins", NYM="New York Mets", NYY="New York Yankees",
           PHI="Philadelphia Phillies", PIT="Pittsburgh Pirates", SD="San Diego Padres", SEA="Seattle Mariners",
           SF="San Francisco Giants", STL="St. Louis Cardinals", TB="Tampa Bay Rays", TEX="Texas Rangers",
           TOR="Toronto Blue Jays", WSH="Washington Nationals")
NFL = dict(ARI="Arizona Cardinals", ATL="Atlanta Falcons", BAL="Baltimore Ravens", BUF="Buffalo Bills",
           CAR="Carolina Panthers", CHI="Chicago Bears", CIN="Cincinnati Bengals", CLE="Cleveland Browns",
           DAL="Dallas Cowboys", DEN="Denver Broncos", DET="Detroit Lions", GB="Green Bay Packers",
           HOU="Houston Texans", IND="Indianapolis Colts", JAX="Jacksonville Jaguars", KC="Kansas City Chiefs",
           LA="Los Angeles Rams", LAR="Los Angeles Rams", LAC="Los Angeles Chargers", LV="Las Vegas Raiders",
           MIA="Miami Dolphins", MIN="Minnesota Vikings", NE="New England Patriots", NO="New Orleans Saints",
           NYG="New York Giants", NYJ="New York Jets", PHI="Philadelphia Eagles", PIT="Pittsburgh Steelers",
           SEA="Seattle Seahawks", SF="San Francisco 49ers", TB="Tampa Bay Buccaneers", TEN="Tennessee Titans",
           WAS="Washington Commanders", WSH="Washington Commanders")
ROOF = dict(open="Open air", retract="Retractable roof", dome="Dome")


def mod(path, name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, path))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def load(path):
    p = os.path.join(ROOT, path)
    return json.load(open(p)) if os.path.exists(p) else {}


def avg(xs, nd=1):
    xs = [x for x in xs if x is not None]
    return round(statistics.mean(xs), nd) if xs else None


def share(part, whole):
    return round(100 * len(part) / len(whole)) if whole else 0


def slug(s):
    s = s.replace("&", " and ").replace("é", "e").replace("ñ", "n")
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def span(games):
    ys = sorted({str(g["d"])[:4] for g in games})
    return ys[0] + "–" + ys[-1] if ys else ""


def by_month(games, order, key="t"):
    rows = []
    for m in order:
        xs = [g[key] for g in games if int(str(g["d"])[4:6]) == m and g.get(key) is not None]
        if len(xs) >= 5:
            rows.append([MON[m - 1], round(statistics.mean(xs)), len(xs)])
    return rows


def split(games, a, b, key, nd=1):
    """(avg in a, n, avg in b, n) or None when either side is thin."""
    xa, xb = [g[key] for g in a if g.get(key) is not None], [g[key] for g in b if g.get(key) is not None]
    if len(xa) < MIN_N or len(xb) < MIN_N:
        return None
    return round(statistics.mean(xa), nd), len(xa), round(statistics.mean(xb), nd), len(xb)


# ------------------------------------------------------------------ MLB
def rel(g):
    """Wind blow-toward angle against the center-field line, -180..180 (0 = straight out)."""
    return (g["rel"] + 180) % 360 - 180


def mlb():
    parks = mod("scripts/parks.py", "parks").PARKS
    hist = load("data/parks_history.json")
    lg = hist.get("_league") or {}
    out = []
    for code, p in parks.items():
        h = hist.get(code)
        if not h or not h.get("games"):
            continue
        g = h["games"]
        air = [x for x in g if not x.get("rc")]            # roof open
        blow = [x for x in air if x["w"] >= 10]
        wout = [x for x in blow if abs(rel(x)) <= 45]
        win = [x for x in blow if abs(rel(x)) >= 135]
        tiles = [["Runs a game", f"{h['avg']['r']:.1f}", f"league {lg.get('r', 0):.1f}"],
                 ["Home runs a game", f"{h['avg']['hr']:.2f}", f"league {lg.get('hr', 0):.2f}"],
                 ["First pitch" if p["roof"] == "open" else "Outside at first pitch",
                  f"{avg([x['t'] for x in g], 0):.0f}°", "average temperature"]]
        if air:
            tiles.append(["Wind", f"{avg([x['w'] for x in air]):.1f} mph", "average, roof open"])
        if p["roof"] != "open":
            tiles.append(["Roof closed", f"{share([x for x in g if x.get('rc')], g)}%", "of games"])
        notes = []
        s = split(g, wout, win, "r")
        if s:
            hr = split(g, wout, win, "hr", 2)
            notes.append(f"Wind blowing out at 10+ mph ({share(wout, air)}% of open-air games): {s[0]} runs and "
                         f"{hr[0]} home runs a game over {s[1]} games. Blowing in ({share(win, air)}%): "
                         f"{s[2]} runs and {hr[2]} home runs over {s[3]}.")
        elif air:
            notes.append(f"Wind reaches 10+ mph in {share(blow, air)}% of open-air games here — "
                         f"too few blowing straight out or straight in to compare the two.")
        s = split(g, [x for x in g if x["t"] >= 85], [x for x in g if x["t"] <= 60], "r")
        if s:
            hr = split(g, [x for x in g if x["t"] >= 85], [x for x in g if x["t"] <= 60], "hr", 2)
            notes.append(f"At 85° or warmer: {s[0]} runs and {hr[0]} home runs a game ({s[1]} games). "
                         f"At 60° or cooler: {s[2]} and {hr[2]} ({s[3]}).")
        # the wind the 3D model draws: the average push, when there is a consistent one
        gd = dict(home=code, dome=p["roof"] == "dome", sky="Clear")
        sx = sum(x["w"] * math.sin(math.radians(x["rel"])) for x in air)
        sy = sum(x["w"] * math.cos(math.radians(x["rel"])) for x in air)
        tot = sum(x["w"] for x in air)
        model = "The outfield wall is drawn to this park's real distances and heights; the stands are not a likeness."
        if tot and math.hypot(sx, sy) / tot >= 0.2 and p["roof"] != "dome":
            ang = round(math.degrees(math.atan2(sx, sy)))
            way = ("out toward center field" if abs(ang) <= 45 else "in from center field" if abs(ang) >= 135
                   else "toward right field" if ang > 0 else "toward left field")
            gd.update(wind=round(avg([x["w"] for x in air])), windAngle=ang)
            notes.append(f"Averaged over every open-air game, the wind here pushes {way}.")
            model += f" The wind shown is this park's average push ({way}), not today's forecast."
        else:
            model += " No wind is drawn: it has no consistent direction here" + (
                " (the roof is fixed)." if p["roof"] == "dome" else ".")
        out.append(dict(id="mlb-" + code.lower(), sport="mlb", name=p["name"], sub=MLB.get(code, code),
                        roof=ROOF.get(p["roof"]), n=len(g), unit="games", span=span(g), tiles=tiles,
                        bars=dict(title="Average first-pitch temperature by month", unit="°",
                                  rows=by_month(g, range(3, 11))),
                        notes=notes, model=model, spec=dict(sport="mlb", g=gd)))
    return out


# ------------------------------------------------------------- football
def football(sport, name, sub, games, dome, roof, lg_pts, months, gd, extra=None):
    retract = roof == ROOF["retract"]       # no record of the roof's position game by game
    air = [] if dome or retract else [x for x in games if not x.get("dome")]
    tiles = [["Points a game", f"{avg([x['pts'] for x in games]):.1f}",
              f"league {lg_pts:.1f}" if lg_pts else "both teams"]]
    if extra:
        tiles.append(extra)
    notes = []
    if air:
        tiles += [["Kickoff", f"{avg([x['t'] for x in air], 0):.0f}°", "average temperature"],
                  ["Wind", f"{avg([x['w'] for x in air]):.1f} mph", "average at kickoff"]]
        windy, calm = [x for x in air if x["w"] >= 15], [x for x in air if x["w"] < 10]
        s = split(air, windy, calm, "pts")
        if s:
            line = (f"Wind at 15+ mph ({share(windy, air)}% of open-air games): {s[0]} points a game over "
                    f"{s[1]} games, against {s[2]} when it is under 10 mph ({s[3]}).")
            pa = split(air, windy, calm, "pa", 0) if sport == "cfb" else None
            if pa:
                line += f" Passing yards: {pa[0]:.0f} against {pa[2]:.0f}."
            notes.append(line)
        else:
            notes.append(f"Wind reaches 15+ mph in {share(windy, air)}% of open-air games here"
                         + (f" ({len(windy)} game{'s' if len(windy) != 1 else ''} — too few to compare)."
                            if windy else "."))
        cold, mild = [x for x in air if x["t"] <= 40], [x for x in air if 55 <= x["t"] <= 75]
        s = split(air, cold, mild, "pts")
        if s:
            notes.append(f"At 40° or colder ({share(cold, air)}% of open-air games): {s[0]} points a game "
                         f"({s[1]} games), against {s[2]} at 55–75° ({s[3]}).")
    elif retract:
        notes.append("Retractable roof: we have no record of whether it was open for each game, "
                     "so no wind or cold splits are quoted here.")
    else:
        notes.append("Played indoors: the weather outside does not reach the field.")
    model = ("A generic stadium, not a likeness: the field" + (" and the roof are" if dome else " is")
             + " right, the stands are not." + ("" if sport == "nfl" else
             " The field is drawn north–south; we do not have this stadium's bearing."))
    return dict(id=f"{sport}-{slug(name)}", sport=sport, name=name, sub=sub, roof=roof, n=len(games),
                unit="games", span=span(games), tiles=tiles,
                bars=dict(title="Average kickoff temperature by month", unit="°",
                          rows=by_month(air, months)) if by_month(air, months) else None,
                notes=notes, model=model, spec=dict(sport=sport, g=gd))


def nfl():
    stadiums = mod("scripts/nfl/stadiums.py", "stadiums").STADIUMS
    hist = load("data/nfl/stadiums_history.json")
    lg = (hist.get("_league") or {}).get("pts")
    groups = {}
    for code, s in stadiums.items():
        if (hist.get(code) or {}).get("games"):
            groups.setdefault(s["name"], []).append(code)
    out = []
    for name, codes in groups.items():
        s = stadiums[codes[0]]
        games = sorted((g for c in codes for g in hist[c]["games"]), key=lambda g: str(g["d"]))
        dome = s["roof"] == "dome"
        out.append(football("nfl", name, " · ".join(NFL.get(c, c) for c in codes), games, dome,
                            ROOF.get(s["roof"]), lg, [9, 10, 11, 12, 1],
                            dict(home=NFL.get(codes[0], codes[0]), homeAb=codes[0], dome=dome, sky="Clear")))
    return out


def cfb():
    hist = load("data/cfb/venues_history.json")
    lg = (hist.get("_league") or {}).get("pts")
    out = []
    for vid, v in hist.items():
        if vid.startswith("_") or not v.get("games"):
            continue
        pa = avg([g.get("pa") for g in v["games"]], 0)
        out.append(football("cfb", v["name"], " · ".join(x for x in (v.get("team"), v.get("conf")) if x),
                            v["games"], bool(v.get("dome")), "Dome" if v.get("dome") else "Open air", lg,
                            [8, 9, 10, 11, 12], dict(home=v.get("team"), dome=bool(v.get("dome")), sky="Clear"),
                            ["Passing yards a game", f"{pa:.0f}", "both teams"] if pa else None))
    return out


# ------------------------------------------------------------------ golf
# The golf history is kept by event. An event that moved keeps only the
# editions played at its current course; one that moves every year keeps none.
PGA_SINCE = {"El Cardonal at Diamante": 2023}
PGA_ROTATES = {"BMW Championship", "Presidents Cup", "PGA Championship", "U.S. Open", "The Open Championship"}


def pga():
    events = mod("scripts/pga/schedule.py", "pga_schedule").EVENTS
    canon = mod("scripts/pga/deep_history.py", "pga_deep").canon_key
    deep = load("data/pga/deep.json")
    out, seen = [], set()
    for e in events:
        if e.get("team") or e["course"] in seen:
            continue
        seen.add(e["course"])
        ed = ((deep.get("events") or {}).get(canon(e["name"])) or {}).get("editions") or {}
        if e["name"] in PGA_ROTATES:
            ed = {}
        winds = [(y, x.get("wind")) for y, x in sorted(ed.items())
                 if x.get("wind") is not None and int(y) >= PGA_SINCE.get(e["course"], 0)]
        h = e["hole"]
        tiles = [["Signature hole", f"No. {h['n']}", f"par {h['par']}, {h['yds']} yards"]]
        notes = []
        if winds:
            windy = [y for y, w in winds if w >= (deep.get("windyMph") or 12)]
            tiles += [["Tournament wind", f"{avg([w for _, w in winds]):.1f} mph", "average across editions"],
                      ["Windy editions", f"{len(windy)} of {len(winds)}", f"{deep.get('windyMph') or 12}+ mph average"]]
            notes.append(f"{len(winds)} edition{'s' if len(winds) != 1 else ''} played here on file "
                         f"({winds[0][0]}–{winds[-1][0]}). "
                         + (f"The wind averaged {deep.get('windyMph') or 12}+ mph in {', '.join(windy)}."
                            if windy else "None of them averaged 12+ mph of wind."))
        else:
            notes.append("No edition at this course on file yet: its weather history builds from here.")
        out.append(dict(id="pga-" + slug(e["course"]), sport="pga", name=e["course"],
                        sub=f"{e['name']} · {e['city']}", roof=None, n=len(winds), unit="editions",
                        span=(winds[0][0] + "–" + winds[-1][0]) if winds else "", tiles=tiles,
                        bars=dict(title="Average wind by edition", unit=" mph",
                                  rows=[[y, round(w, 1), 1] for y, w in winds]) if len(winds) > 1 else None,
                        notes=notes,
                        model=f"Hole {h['n']} drawn from its par, yardage, dogleg and water — a sketch of how "
                              f"it plays, not a survey of the course.",
                        spec=dict(sport="pga", event=dict(hole=h), g={})))
    return out


# ---------------------------------------------------------------- NASCAR
def nascar():
    races = mod("scripts/nascar/schedule.py", "nascar_schedule").RACES
    track_of = mod("scripts/nascar/deep_history.py", "nascar_deep").track_of
    deep = load("data/nascar/deep.json")
    kinds = dict(SS="Superspeedway", INT="Intermediate", SHORT="Short track", ST="Short track",
                 ROAD="Road course", FLAT="Flat track")
    out, seen = [], set()
    for r in races:
        if r["track"] in seen:
            continue
        seen.add(r["track"])
        hit = track_of(r["track"]) or track_of(r["name"])
        key = hit[0] if hit else None
        past = [x for x in deep.get("races") or [] if x.get("track") == key and x.get("hi") is not None]
        sh = r["shape"]
        kind = kinds.get(hit[1] if hit else "", "")
        tiles = [["Track", f"{sh['mi']} mi", f"{sh.get('bank', 0)}° banking" + (f" · {kind}" if kind else "")]]
        notes = []
        if past:
            hot = [x for x in past if x.get("hot")]
            tiles += [["Race-day high", f"{avg([x['hi'] for x in past], 0):.0f}°", "average"],
                      ["Hot races", f"{len(hot)} of {len(past)}", f"{deep.get('hotF') or 88}°+ highs"]]
            hi, lo = max(past, key=lambda x: x["hi"]), min(past, key=lambda x: x["hi"])
            notes.append(f"{len(past)} Cup races here on file ({past[0]['y']}–{past[-1]['y']}). Hottest: "
                         f"{hi['hi']}° on {hi['d']}. Coolest: {lo['hi']}° on {lo['d']}.")
        else:
            notes.append("No Cup race here in our history sample yet.")
        rows = []
        for y in sorted({x["y"] for x in past}):
            ys = [x["hi"] for x in past if x["y"] == y]
            rows.append([str(y), round(statistics.mean(ys)), len(ys)])
        out.append(dict(id="nascar-" + slug(r["track"]), sport="nascar", name=r["track"], sub=r["city"],
                        roof=None, n=len(past), unit="races", span=(f"{past[0]['y']}–{past[-1]['y']}" if past else ""),
                        tiles=tiles,
                        bars=dict(title="Race-day high by season", unit="°", rows=rows) if len(rows) > 1 else None,
                        notes=notes,
                        model="The track's shape class, length and banking are right; the grandstands are generic.",
                        spec=dict(sport="nascar", g=dict(shape=sh, time="3:00 PM ET", sky="Clear"))))
    return out


# ----------------------------------------------------------------- pages
def page(tpl, v):
    title = f"{v['name']} Weather History — {v['sub'].split(' · ')[0]} | DFSRADAR Venue Atlas"
    desc = (f"{v['name']} in 3D with its weather history: " + " ".join(v["notes"]))[:300]
    url = f"{BASE}/atlas/{v['slug']}/"
    t = tpl.replace("../assets/", "../../assets/").replace('src="atlas.js', 'src="../atlas.js')
    t = re.sub(r"<title>.*?</title>", "<title>" + html.escape(title) + "</title>", t, count=1, flags=re.S)
    t = re.sub(r'(<meta name="description" content=")[^"]*', lambda m: m.group(1) + html.escape(desc), t, count=1)
    t = re.sub(r'(<meta property="og:title" content=")[^"]*', lambda m: m.group(1) + html.escape(title), t, count=1)
    t = re.sub(r'(<meta property="og:description" content=")[^"]*', lambda m: m.group(1) + html.escape(desc), t, count=1)
    t = t.replace(f"{BASE}/atlas/", url)
    t = t.replace('<main class="wrap" id="atlas">', f'<main class="wrap" id="atlas" data-venue="{v["id"]}">')
    seo = (f"<h1>{html.escape(v['name'])}</h1><p>{html.escape(v['sub'])}</p>"
           + "".join(f"<p>{html.escape(n)}</p>" for n in v["notes"]))
    return re.sub(r'<div id="atlas-seo">.*?</div>', lambda m: '<div id="atlas-seo">' + seo + "</div>", t, count=1, flags=re.S)


def main():
    venues = []
    for fn in (mlb, nfl, cfb, pga, nascar):
        try:
            got = fn()
            print(f"{fn.__name__}: {len(got)} venues")
            venues += got
        except Exception as e:                      # one sport's files missing must not sink the rest
            print(f"::warning title=Atlas::{fn.__name__} skipped ({e})")
    used = set()
    for v in venues:
        s = slug(v["name"])
        if s in used:
            s = slug(v["name"] + " " + v["sub"].split(" · ")[0])
        used.add(s)
        v["slug"] = s
    if len(venues) < 50:
        sys.exit("::error::the Atlas found fewer than 50 venues — not publishing a thin one")
    os.makedirs(OUT, exist_ok=True)
    built = datetime.now().strftime("%Y-%m-%d")
    json.dump(dict(built=built, venues=venues), open(os.path.join(OUT, "data.json"), "w"),
              separators=(",", ":"), ensure_ascii=False)
    tpl = open(os.path.join(OUT, "index.html"), encoding="utf-8").read()
    for v in venues:
        d = os.path.join(OUT, v["slug"])
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "index.html"), "w", encoding="utf-8") as f:
            f.write(page(tpl, v))
    urls = [f"{BASE}/atlas/"] + [f"{BASE}/atlas/{v['slug']}/" for v in venues]
    with open(os.path.join(OUT, "sitemap.xml"), "w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                + "".join(f"<url><loc>{u}</loc><lastmod>{built}</lastmod></url>\n" for u in urls) + "</urlset>\n")
    print(f"wrote {len(venues)} venues, {len(venues)} pages and the sitemap")


if __name__ == "__main__":
    main()
