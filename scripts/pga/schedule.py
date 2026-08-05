"""Curated 2026 PGA Tour schedule (remaining season) — no API dependency.

Each event: tournament name, course, city, coordinates, IANA timezone, and
round dates (r1 = Thursday, end = Sunday). Team events flagged.

Refresh yearly when the new schedule drops (source: pgatour.com schedule
announcements). Dates below are the 2026 playoffs + FedExCup Fall.
"""

EVENTS = [
    dict(name="FedEx St. Jude Championship", course="TPC Southwind",
         city="Memphis, TN", lat=35.062, lon=-89.853, tz="America/Chicago",
         r1="2026-08-13", end="2026-08-16", team=False),
    dict(name="BMW Championship", course="Bellerive Country Club",
         city="Town and Country, MO", lat=38.632, lon=-90.438, tz="America/Chicago",
         r1="2026-08-20", end="2026-08-23", team=False),
    dict(name="TOUR Championship", course="East Lake Golf Club",
         city="Atlanta, GA", lat=33.740, lon=-84.308, tz="America/New_York",
         r1="2026-08-27", end="2026-08-30", team=False),
    dict(name="Biltmore Championship", course="The Cliffs at Walnut Cove",
         city="Asheville, NC", lat=35.438, lon=-82.525, tz="America/New_York",
         r1="2026-09-17", end="2026-09-20", team=False),
    dict(name="Presidents Cup", course="Medinah Country Club",
         city="Medinah, IL", lat=41.973, lon=-88.045, tz="America/Chicago",
         r1="2026-09-24", end="2026-09-27", team=True),
    dict(name="Bank of Utah Championship", course="Black Desert Resort GC",
         city="Ivins, UT", lat=37.168, lon=-113.679, tz="America/Denver",
         r1="2026-10-01", end="2026-10-04", team=False),
    dict(name="Baycurrent Classic", course="Yokohama Country Club",
         city="Yokohama, Japan", lat=35.383, lon=139.532, tz="Asia/Tokyo",
         r1="2026-10-08", end="2026-10-11", team=False),
    dict(name="Butterfield Bermuda Championship", course="Port Royal Golf Course",
         city="Southampton, Bermuda", lat=32.253, lon=-64.863, tz="Atlantic/Bermuda",
         r1="2026-10-22", end="2026-10-25", team=False),
    dict(name="VidantaWorld Mexico Open", course="Vidanta Vallarta",
         city="Puerto Vallarta, Mexico", lat=20.691, lon=-105.294, tz="America/Bahia_Banderas",
         r1="2026-10-29", end="2026-11-01", team=False),
    dict(name="World Wide Technology Championship", course="El Cardonal at Diamante",
         city="Los Cabos, Mexico", lat=22.903, lon=-110.021, tz="America/Mazatlan",
         r1="2026-11-05", end="2026-11-08", team=False),
    dict(name="Good Good Championship", course="Omni Barton Creek (Fazio Canyons)",
         city="Austin, TX", lat=30.293, lon=-97.872, tz="America/Chicago",
         r1="2026-11-12", end="2026-11-15", team=False),
    dict(name="The RSM Classic", course="Sea Island GC (Seaside)",
         city="St. Simons Island, GA", lat=31.152, lon=-81.390, tz="America/New_York",
         r1="2026-11-19", end="2026-11-22", team=False),
]
