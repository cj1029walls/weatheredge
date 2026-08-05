"""NFL stadium metadata for DFSRADAR.

bearing = compass direction of the field's long axis (either end works — the
axis is symmetric), curated approximations (±15°). For football what matters
is wind relative to that axis: along-field helps/hurts kicking and deep
passing directionally; crosswind hurts both.

roof: open / retract / dome.  since/exclude mirror the MLB parks file —
seasons before a team's current stadium are dropped from history.
"""

STADIUMS = {
    "ARI": dict(name="State Farm Stadium",     lat=33.5276, lon=-112.2626, tz="America/Phoenix",    bearing=90,  roof="retract", since=2015, exclude=[]),
    "ATL": dict(name="Mercedes-Benz Stadium",  lat=33.7554, lon=-84.4008,  tz="America/New_York",   bearing=0,   roof="retract", since=2017, exclude=[]),
    "BAL": dict(name="M&T Bank Stadium",       lat=39.2780, lon=-76.6227,  tz="America/New_York",   bearing=0,   roof="open",    since=2015, exclude=[]),
    "BUF": dict(name="Highmark Stadium",       lat=42.7738, lon=-78.7870,  tz="America/New_York",   bearing=60,  roof="open",    since=2015, exclude=[]),
    "CAR": dict(name="Bank of America Stadium",lat=35.2258, lon=-80.8528,  tz="America/New_York",   bearing=45,  roof="open",    since=2015, exclude=[]),
    "CHI": dict(name="Soldier Field",          lat=41.8623, lon=-87.6167,  tz="America/Chicago",    bearing=0,   roof="open",    since=2015, exclude=[]),
    "CIN": dict(name="Paycor Stadium",         lat=39.0955, lon=-84.5161,  tz="America/New_York",   bearing=0,   roof="open",    since=2015, exclude=[]),
    "CLE": dict(name="Huntington Bank Field",  lat=41.5061, lon=-81.6995,  tz="America/New_York",   bearing=135, roof="open",    since=2015, exclude=[]),
    "DAL": dict(name="AT&T Stadium",           lat=32.7473, lon=-97.0945,  tz="America/Chicago",    bearing=90,  roof="retract", since=2015, exclude=[]),
    "DEN": dict(name="Empower Field",          lat=39.7439, lon=-105.0201, tz="America/Denver",     bearing=0,   roof="open",    since=2015, exclude=[]),
    "DET": dict(name="Ford Field",             lat=42.3400, lon=-83.0456,  tz="America/Detroit",    bearing=45,  roof="dome",    since=2015, exclude=[]),
    "GB":  dict(name="Lambeau Field",          lat=44.5013, lon=-88.0622,  tz="America/Chicago",    bearing=0,   roof="open",    since=2015, exclude=[]),
    "HOU": dict(name="NRG Stadium",            lat=29.6847, lon=-95.4107,  tz="America/Chicago",    bearing=0,   roof="retract", since=2015, exclude=[]),
    "IND": dict(name="Lucas Oil Stadium",      lat=39.7601, lon=-86.1639,  tz="America/Indiana/Indianapolis", bearing=0, roof="retract", since=2015, exclude=[]),
    "JAX": dict(name="EverBank Stadium",       lat=30.3239, lon=-81.6373,  tz="America/New_York",   bearing=0,   roof="open",    since=2015, exclude=[]),
    "KC":  dict(name="GEHA Field at Arrowhead",lat=39.0489, lon=-94.4839,  tz="America/Chicago",    bearing=0,   roof="open",    since=2015, exclude=[]),
    "LV":  dict(name="Allegiant Stadium",      lat=36.0909, lon=-115.1833, tz="America/Los_Angeles",bearing=0,   roof="dome",    since=2020, exclude=[]),
    "LAC": dict(name="SoFi Stadium",           lat=33.9535, lon=-118.3392, tz="America/Los_Angeles",bearing=0,   roof="dome",    since=2020, exclude=[]),
    "LA":  dict(name="SoFi Stadium",           lat=33.9535, lon=-118.3392, tz="America/Los_Angeles",bearing=0,   roof="dome",    since=2020, exclude=[]),
    "MIA": dict(name="Hard Rock Stadium",      lat=25.9580, lon=-80.2389,  tz="America/New_York",   bearing=90,  roof="open",    since=2015, exclude=[]),
    "MIN": dict(name="U.S. Bank Stadium",      lat=44.9738, lon=-93.2577,  tz="America/Chicago",    bearing=90,  roof="dome",    since=2016, exclude=[]),
    "NE":  dict(name="Gillette Stadium",       lat=42.0909, lon=-71.2643,  tz="America/New_York",   bearing=0,   roof="open",    since=2015, exclude=[]),
    "NO":  dict(name="Caesars Superdome",      lat=29.9511, lon=-90.0812,  tz="America/Chicago",    bearing=0,   roof="dome",    since=2015, exclude=[]),
    "NYG": dict(name="MetLife Stadium",        lat=40.8135, lon=-74.0745,  tz="America/New_York",   bearing=20,  roof="open",    since=2015, exclude=[]),
    "NYJ": dict(name="MetLife Stadium",        lat=40.8135, lon=-74.0745,  tz="America/New_York",   bearing=20,  roof="open",    since=2015, exclude=[]),
    "PHI": dict(name="Lincoln Financial Field",lat=39.9008, lon=-75.1675,  tz="America/New_York",   bearing=0,   roof="open",    since=2015, exclude=[]),
    "PIT": dict(name="Acrisure Stadium",       lat=40.4468, lon=-80.0158,  tz="America/New_York",   bearing=0,   roof="open",    since=2015, exclude=[]),
    "SEA": dict(name="Lumen Field",            lat=47.5952, lon=-122.3316, tz="America/Los_Angeles",bearing=0,   roof="open",    since=2015, exclude=[]),
    "SF":  dict(name="Levi's Stadium",         lat=37.4030, lon=-121.9700, tz="America/Los_Angeles",bearing=0,   roof="open",    since=2015, exclude=[]),
    "TB":  dict(name="Raymond James Stadium",  lat=27.9759, lon=-82.5033,  tz="America/New_York",   bearing=0,   roof="open",    since=2015, exclude=[]),
    "TEN": dict(name="Nissan Stadium",         lat=36.1665, lon=-86.7713,  tz="America/Chicago",    bearing=0,   roof="open",    since=2015, exclude=[]),
    "WAS": dict(name="Northwest Stadium",      lat=38.9078, lon=-76.8645,  tz="America/New_York",   bearing=340, roof="open",    since=2015, exclude=[]),
}

# nflverse team code quirks: LA = Rams, LAC = Chargers, OAK pre-2020, SD pre-2017, STL pre-2016
OLD_CODES = {"OAK": None, "SD": None, "STL": None}   # dropped eras


def axis_angle(wind_dir_deg, bearing):
    """0 = wind straight down the field axis, 90 = pure crosswind."""
    d = (wind_dir_deg - bearing) % 180
    return min(d, 180 - d)


def wind_class(ax):
    return "along" if ax <= 30 else "cross" if ax >= 60 else "angled"
