#!/usr/bin/env python3
"""DFSRADAR — "RADAR Flag of the Day" generator.

Reads the free MLB radar's slate (site/data.json, full or slimmed) and picks
tonight's single strongest weather/park flag for the daily free tweet, plus
the count of remaining board flags for the tease line.

The tease structure (one flag fully free with a real number, the rest named
but not revealed) is the product: never invent a stat — every number comes
straight from the radar's history-match engine.

Flag rules (a game is a "board flag" when, non-dome):
  * |HR delta vs park norm| >= 20%  (history match, sample >= 15), or
  * an O/U LEAN call (median of matched games clears the line by >= 1 run), or
  * a suppressor: HR delta <= -15% (these are the stack-killers)

Headline pick = highest-scoring flag:
  score = |hr| * min(1, sample/30)  + 15 if EXTREME wind park and wind >= 8
          + 10 if wind label starts OUT/IN (aligned wind story)
Suppressors compete equally — a big wind-in fade IS the flag some nights.

Only main-slate games are considered (first pitch 6:35 PM ET or later —
CJ's standing rule; override with --all).

Usage:
  python3 flag_of_day.py slate.json            # full site/data.json
  python3 flag_of_day.py slate.json --slim     # slimmed field names (a,h,pk,...)
Prints the pick + tweet draft, writes flag_pick.json next to the input.
"""
import json, os, re, sys
from datetime import datetime

MAIN_SLATE_MIN = 18 * 60 + 35   # 6:35 PM ET


def start_minutes(tm):
    m = re.match(r"(\d+):(\d+)\s*(AM|PM)", str(tm or ""))
    if not m:
        return None
    hh, mm, ap = int(m.group(1)), int(m.group(2)), m.group(3)
    if ap == "PM" and hh != 12:
        hh += 12
    if ap == "AM" and hh == 12:
        hh = 0
    return hh * 60 + mm


def norm(g, slim):
    if slim:
        return dict(away=g["a"], home=g["h"], park=g["pk"], time=g["tm"],
                    temp=g["t"], wind=g["w"], dir=g["dir"], windLabel=g["wl"],
                    dome=bool(g["dm"]), sample=g["n"], hr=g["hr"], runs=g["ru"],
                    hrGm=g["hg"], hrPark=g["hp"], mlbHr=g.get("mh"),
                    ou=g.get("ou"), total=g.get("tot"), ouMedian=g.get("om"),
                    ouLean=g.get("ol"), windFx=g.get("wf"), delay=g.get("dl"))
    return dict(away=g["away"], home=g["home"], park=g["park"], time=g["time"],
                temp=g["temp"], wind=g["wind"], dir=g["dir"],
                windLabel=g["windLabel"], dome=bool(g["dome"]),
                sample=g["sample"], hr=g["hr"], runs=g["runs"], hrGm=g["hrGm"],
                hrPark=g["hrPark"], mlbHr=(g.get("mlb") or {}).get("hr"),
                ou=g.get("ou"), total=g.get("total"), ouMedian=g.get("ouMedian"),
                ouLean=g.get("ouLean"), windFx=g.get("windFx"),
                delay=(g.get("delay") or {}).get("level"))


def is_flag(g):
    if g["dome"] or g["sample"] < 15:
        return False
    if abs(g["hr"]) >= 20:
        return True
    if g["hr"] <= -15:
        return True
    if g["ouLean"] and g["ouMedian"] is not None and g["total"] \
            and abs(g["ouMedian"] - g["total"]) >= 1.0:
        return True
    return False


def score(g):
    s = abs(g["hr"]) * min(1.0, g["sample"] / 30)
    wf = g.get("windFx") or {}
    if wf.get("rating") == "EXTREME" and g["wind"] >= 8:
        s += 15
    if str(g["windLabel"] or "").startswith(("OUT", "IN")):
        s += 10
    if g["ouLean"]:               # the board itself calls a lean — corroboration
        s += 8
    if g["temp"] is not None and g["temp"] >= 85:
        s += 5                    # heat story: hot air carries
    return s


def main():
    path = sys.argv[1]
    slim = "--slim" in sys.argv
    data = json.load(open(path))
    games = [norm(g, slim) for g in (data["games"] if isinstance(data, dict) else data)]
    if "--all" not in sys.argv:
        games = [g for g in games if (start_minutes(g["time"]) or 0) >= MAIN_SLATE_MIN]
        print(f"main slate (6:35 PM ET+): {len(games)} games")
    flags = [g for g in games if is_flag(g)]
    if not flags:
        print("No board flags tonight — quiet slate, skip the post or run a "
              "record/receipts tweet instead.")
        return
    flags.sort(key=score, reverse=True)
    pick, others = flags[0], flags[1:]
    suppressors = [g for g in others if g["hr"] <= -15]

    d = datetime.now().strftime("%-m/%-d")
    wdir = {"LF": "left", "CF": "center", "RF": "right"}.get(
        str(pick["windLabel"]).split()[-1], "")
    updown = "+" if pick["hr"] > 0 else ""
    wind_story = (f"Wind blowing out to {wdir}" if pick["windLabel"].startswith("OUT")
                  else f"Wind blowing in from {wdir}" if pick["windLabel"].startswith("IN")
                  else f"{pick['wind']} mph crosswind")
    park_short = pick["park"].split(" · ")[0]
    wf = pick.get("windFx") or {}
    windy_story = (str(pick["windLabel"] or "").startswith(("OUT", "IN"))
                   and pick["wind"] >= 8)
    lines = [f"🚨 RADAR FLAG — {d}", ""]
    if windy_story:
        lines.append(f"{wind_story} at {park_short} tonight ({pick['wind']} mph). "
                     f"{pick['sample']} similar-condition games there: "
                     f"HR rate {updown}{pick['hr']}% vs park norm "
                     f"({pick['hrGm']}/gm vs {round(pick['hrPark'],1)}).")
        if wf.get("rating") == "EXTREME":
            lines += ["", f"Most wind-sensitive park we track: "
                          f"{'+' if wf['pct10']>0 else ''}{wf['pct10']}% HR per 10 mph."]
    else:
        opener = (f"{pick['temp']}° at first pitch for {pick['away']}-{pick['home']} "
                  f"at {park_short}." if (pick["temp"] or 0) >= 85 else
                  f"{pick['away']}-{pick['home']} at {park_short} tonight.")
        lines.append(f"{opener} {pick['sample']} similar-condition games there: "
                     f"HR rate {updown}{pick['hr']}% vs park norm "
                     f"({pick['hrGm']}/gm vs {round(pick['hrPark'],1)}).")
        if pick["ouLean"] and pick["ouMedian"] and pick["total"]:
            pctside = pick["ou"][pick["ouLean"]] if pick.get("ou") else None
            lines += ["", f"The total sits {pick['total']}. Median of those "
                          f"{pick['sample']} games: {pick['ouMedian']} runs"
                          + (f" — {pctside}% went {pick['ouLean']}." if pctside else ".")]
    lines.append("")
    tease = f"Tonight's board: {len(flags)} flags."
    if suppressors:
        tease += " One kills a popular stack."
    lines += [tease, "", "📡 dfsradar.com"]
    tweet = "\n".join(lines)
    if len(tweet) > 280:   # trim the parenthetical rates first
        tweet = tweet.replace(f" ({pick['hrGm']}/gm vs {round(pick['hrPark'],1)})", "")

    out = dict(date=d, pick=pick, tweet=tweet, nFlags=len(flags),
               others=[dict(m=f"{g['away']}@{g['home']}", hr=g["hr"],
                            lean=g["ouLean"]) for g in others],
               suppressor=(dict(m=f"{suppressors[0]['away']}@{suppressors[0]['home']}",
                                hr=suppressors[0]["hr"]) if suppressors else None))
    op = os.path.join(os.path.dirname(os.path.abspath(path)), "flag_pick.json")
    json.dump(out, open(op, "w"), indent=1)
    print(f"PICK: {pick['away']} @ {pick['home']} — {pick['park']} · "
          f"score {round(score(pick),1)}")
    print(f"FLAGS ON BOARD: {len(flags)} "
          f"({', '.join(f['away']+'@'+f['home'] for f in flags)})")
    if suppressors:
        print(f"STACK-KILLER: {suppressors[0]['away']}@{suppressors[0]['home']} "
              f"{suppressors[0]['hr']}%")
    print(f"\nTWEET ({len(tweet)} chars):\n{tweet}")
    print(f"\nwrote {op}")


if __name__ == "__main__":
    main()
