"""Sportsbook price helpers shared by the props builders.

American odds can't be averaged directly: they jump from -100 to +100, so the
median of [-110, +105] comes out as -2.5 -- not a price at all (that's how
"-28 / -8" strikeout prices and a "0" receptions price reached the boards).
Everything here works in implied probability and converts back.

    median_price([-110, 105])      -> -102   (the median book's number)
    best_price([(-110,'A'),(105,'B')]) -> (105, 'B')   (highest payout for the bettor)
    consensus_line(points)         -> the line most books hang (ties: the median)
"""
import statistics


def valid(a):
    """A usable American price: +100 or longer, -100 or shorter."""
    try:
        a = float(a)
    except (TypeError, ValueError):
        return False
    return a >= 100 or a <= -100


def to_prob(a):
    """American odds -> implied probability (0-1), vig included."""
    a = float(a)
    return 100.0 / (a + 100.0) if a > 0 else -a / (-a + 100.0)


def to_american(p):
    """Implied probability (0-1) -> American odds, rounded to a whole number."""
    p = min(max(float(p), 1e-6), 1 - 1e-6)
    if p >= 0.5:
        return -int(round(100.0 * p / (1.0 - p)))
    return int(round(100.0 * (1.0 - p) / p))


def median_price(prices):
    """Median price across books, taken in probability space. None if nothing valid."""
    ps = [to_prob(a) for a in prices if valid(a)]
    if not ps:
        return None
    return to_american(statistics.median(ps))


def payout(a):
    """Profit on a 1-unit stake at American price a."""
    a = float(a)
    return a / 100.0 if a > 0 else 100.0 / -a


def best_price(rows):
    """rows: iterable of (price, book) -> (price, book) paying the most, or None."""
    rows = [(int(a), b) for a, b in rows if valid(a)]
    if not rows:
        return None
    return max(rows, key=lambda r: payout(r[0]))


def consensus_line(points):
    """The line most books hang; on a tie, the one nearest the median line."""
    pts = [float(x) for x in points if x is not None]
    if not pts:
        return None
    counts = {}
    for x in pts:
        counts[x] = counts.get(x, 0) + 1
    top = max(counts.values())
    modes = [x for x, n in counts.items() if n == top]
    med = statistics.median(pts)
    line = min(modes, key=lambda x: (abs(x - med), x))
    return line


def implied_pct(a):
    """American odds -> implied probability in percent (1 decimal), None if unusable."""
    return round(to_prob(a) * 100, 1) if valid(a) else None
