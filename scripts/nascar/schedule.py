"""Curated 2026 NASCAR Cup Series schedule (remaining season) — no API
dependency.

Each race: name, track, city, race date, scheduled green flag (ET), track
coordinates, IANA timezone. All remaining 2026 points races run on OVALS
(Charlotte's fall race returned to the oval layout in 2026), so rain means
no racing — the delay outlook is the headline number.

Refresh yearly when the new schedule drops (source: jayski.com / nascar.com).
"""

RACES = [
    dict(name="Iowa Corn 350", track="Iowa Speedway", city="Newton, IA",
         date="2026-08-09", et="15:30", lat=41.674, lon=-93.014, tz="America/Chicago"),
    dict(name="Cook Out 400", track="Richmond Raceway", city="Richmond, VA",
         date="2026-08-15", et="19:00", lat=37.592, lon=-77.420, tz="America/New_York"),
    dict(name="Dollar Tree 301", track="New Hampshire Motor Speedway", city="Loudon, NH",
         date="2026-08-23", et="15:00", lat=43.363, lon=-71.461, tz="America/New_York"),
    dict(name="Coke Zero Sugar 400", track="Daytona International Speedway", city="Daytona Beach, FL",
         date="2026-08-29", et="19:30", lat=29.185, lon=-81.070, tz="America/New_York"),
    dict(name="Cook Out Southern 500", track="Darlington Raceway", city="Darlington, SC",
         date="2026-09-06", et="17:00", lat=34.295, lon=-79.905, tz="America/New_York", playoff=True),
    dict(name="Enjoy Illinois 300", track="World Wide Technology Raceway", city="Madison, IL",
         date="2026-09-13", et="15:00", lat=38.651, lon=-90.137, tz="America/Chicago", playoff=True),
    dict(name="Bass Pro Shops Night Race", track="Bristol Motor Speedway", city="Bristol, TN",
         date="2026-09-19", et="19:30", lat=36.516, lon=-82.257, tz="America/New_York", playoff=True),
    dict(name="Hollywood Casino 400", track="Kansas Speedway", city="Kansas City, KS",
         date="2026-09-27", et="15:00", lat=39.116, lon=-94.831, tz="America/Chicago", playoff=True),
    dict(name="South Point 400", track="Las Vegas Motor Speedway", city="Las Vegas, NV",
         date="2026-10-04", et="17:30", lat=36.272, lon=-115.010, tz="America/Los_Angeles", playoff=True),
    dict(name="Bank of America 400", track="Charlotte Motor Speedway", city="Concord, NC",
         date="2026-10-11", et="15:00", lat=35.352, lon=-80.683, tz="America/New_York", playoff=True),
    dict(name="Phoenix Fall Race", track="Phoenix Raceway", city="Avondale, AZ",
         date="2026-10-18", et="15:00", lat=33.375, lon=-112.311, tz="America/Phoenix", playoff=True),
    dict(name="YellaWood 500", track="Talladega Superspeedway", city="Talladega, AL",
         date="2026-10-25", et="14:00", lat=33.566, lon=-86.066, tz="America/Chicago", playoff=True),
    dict(name="Xfinity 500", track="Martinsville Speedway", city="Martinsville, VA",
         date="2026-11-01", et="14:00", lat=36.634, lon=-79.851, tz="America/New_York", playoff=True),
    dict(name="NASCAR Cup Series Championship", track="Homestead-Miami Speedway", city="Homestead, FL",
         date="2026-11-08", et="15:00", lat=25.452, lon=-80.409, tz="America/New_York", playoff=True),
]
