"""Shared Odds API outright-market join for PGA / NASCAR PRO leans.

Golf and NASCAR don't trade player props the way football does — the market
is outrights (tournament / race winner). This helper attaches the market's
winner price + implied probability to each lean's named player/driver, so a
lean card can show OUR ranking next to THEIR price. Display-only market
context: we never invent a win probability of our own.

Everything is guarded: Odds API sport keys for golf are event-specific and
come and go; a missing key or failed call just means leans post unpriced.
"""
import json, os, re, unicodedata, urllib.request

SPORTS_URL = "https://api.the-odds-api.com/v4/sports?apiKey={key}&all=false"
ODDS_URL = ("https://api.the-odds-api.com/v4/sports/{skey}/odds"
            "?apiKey={key}&regions=us&markets=outrights&oddsFormat=american")


def _get(url, timeout=45):
    req = urllib.request.Request(url, headers={"User-Agent": "dfsradar-build/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _norm(nm):
    nm = unicodedata.normalize("NFKD", nm or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z ]", "", nm.lower()).strip()


def _implied(price):
    if price is None:
        return None
    return round(100 / (price + 100) * 100, 1) if price > 0 else \
        round(-price / (-price + 100) * 100, 1)


def attach_outright_prices(leans, sport_hint, log=print):
    """Attach dict(price, implied) as lean['market'] where the outright market
    has the lean's `who`. Returns count priced."""
    key = os.environ.get("ODDS_API_KEY")
    named = [l for l in leans if l.get("who")]
    if not key or not named:
        log(f"outrights: skipped (no key or no named leans)")
        return 0
    try:
        sports = _get(SPORTS_URL.format(key=key))
    except Exception as e:
        log(f"outrights: sports list unavailable ({e})")
        return 0
    keys = [s["key"] for s in sports
            if s.get("active") and sport_hint in (s.get("key") or "")
            and s.get("has_outrights")]
    if not keys:
        log(f"outrights: no active '{sport_hint}' outright market this week")
        return 0
    prices = {}
    for skey in keys[:2]:                     # at most two event markets
        try:
            data = _get(ODDS_URL.format(skey=skey, key=key))
        except Exception as e:
            log(f"outrights: {skey} unavailable ({e})")
            continue
        for ev in data:
            for bk in ev.get("bookmakers", []):
                for mk in bk.get("markets", []):
                    if mk.get("key") != "outrights":
                        continue
                    for oc in mk.get("outcomes", []):
                        nm = _norm(oc.get("name"))
                        if nm and oc.get("price") is not None:
                            prices.setdefault(nm, []).append(oc["price"])
    priced = 0
    for l in named:
        rows = prices.get(_norm(l["who"]))
        if not rows:
            continue
        rows.sort()
        med = rows[len(rows) // 2]
        l["market"] = dict(price=int(med), implied=_implied(med))
        priced += 1
    log(f"outrights: priced {priced}/{len(named)} leans from {len(keys[:2])} market(s)")
    return priced
