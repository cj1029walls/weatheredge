"""Park metadata for all 30 MLB clubs — the single source of truth for the pipeline.

Fields per team code:
  name        current park name
  lat, lon    coordinates for weather lookups
  tz          IANA timezone of the park
  bearing     compass bearing (deg from true north) of the home-plate -> center-field
              line. CURATED APPROXIMATIONS (±10-15° is fine: wind sectors are 90° wide).
  roof        'open' | 'retract' | 'dome'
  since       first season in the history sample: the later of 2015 and the
              park's actual first season (ATL 2017, TEX 2020, ATH 2025)
  exclude     seasons to drop from history (COVID relocations, temporary parks)
  retro       Retrosheet home-team code(s)
  mlbid       statsapi team id
"""

PARKS = {
    "ARI": dict(name="Chase Field",              lat=33.4453, lon=-112.0667, tz="America/Phoenix",    bearing=0,   roof="retract", since=2015, exclude=[], retro=["ARI"], mlbid=109),
    "ATH": dict(name="Sutter Health Park",       lat=38.5804, lon=-121.5133, tz="America/Los_Angeles",bearing=60,  roof="open",    since=2025, exclude=[], retro=["ATH","OAK"], mlbid=133),
    "ATL": dict(name="Truist Park",              lat=33.8907, lon=-84.4677,  tz="America/New_York",   bearing=45,  roof="open",    since=2017, exclude=[], retro=["ATL"], mlbid=144),
    "BAL": dict(name="Camden Yards",             lat=39.2839, lon=-76.6217,  tz="America/New_York",   bearing=30,  roof="open",    since=2015, exclude=[], retro=["BAL"], mlbid=110),
    "BOS": dict(name="Fenway Park",              lat=42.3467, lon=-71.0972,  tz="America/New_York",   bearing=45,  roof="open",    since=2015, exclude=[], retro=["BOS"], mlbid=111),
    "CHC": dict(name="Wrigley Field",            lat=41.9484, lon=-87.6553,  tz="America/Chicago",    bearing=40,  roof="open",    since=2015, exclude=[], retro=["CHN"], mlbid=112),
    "CIN": dict(name="Great American Ball Park", lat=39.0975, lon=-84.5066,  tz="America/New_York",   bearing=120, roof="open",    since=2015, exclude=[], retro=["CIN"], mlbid=113),
    "CLE": dict(name="Progressive Field",        lat=41.4962, lon=-81.6852,  tz="America/New_York",   bearing=0,   roof="open",    since=2015, exclude=[], retro=["CLE"], mlbid=114),
    "COL": dict(name="Coors Field",              lat=39.7559, lon=-104.9942, tz="America/Denver",     bearing=5,   roof="open",    since=2015, exclude=[], retro=["COL"], mlbid=115),
    "CWS": dict(name="Rate Field",               lat=41.8300, lon=-87.6338,  tz="America/Chicago",    bearing=135, roof="open",    since=2015, exclude=[], retro=["CHA"], mlbid=145),
    "DET": dict(name="Comerica Park",            lat=42.3390, lon=-83.0485,  tz="America/Detroit",    bearing=145, roof="open",    since=2015, exclude=[], retro=["DET"], mlbid=116),
    "HOU": dict(name="Daikin Park",              lat=29.7573, lon=-95.3555,  tz="America/Chicago",    bearing=345, roof="retract", since=2015, exclude=[], retro=["HOU"], mlbid=117),
    "KC":  dict(name="Kauffman Stadium",         lat=39.0517, lon=-94.4803,  tz="America/Chicago",    bearing=45,  roof="open",    since=2015, exclude=[], retro=["KCA"], mlbid=118),
    "LAA": dict(name="Angel Stadium",            lat=33.8003, lon=-117.8827, tz="America/Los_Angeles",bearing=65,  roof="open",    since=2015, exclude=[], retro=["ANA"], mlbid=108),
    "LAD": dict(name="Dodger Stadium",           lat=34.0739, lon=-118.2400, tz="America/Los_Angeles",bearing=25,  roof="open",    since=2015, exclude=[], retro=["LAN"], mlbid=119),
    "MIA": dict(name="loanDepot park",           lat=25.7781, lon=-80.2196,  tz="America/New_York",   bearing=75,  roof="retract", since=2015, exclude=[], retro=["MIA"], mlbid=146),
    "MIL": dict(name="American Family Field",    lat=43.0280, lon=-87.9712,  tz="America/Chicago",    bearing=130, roof="retract", since=2015, exclude=[], retro=["MIL"], mlbid=158),
    "MIN": dict(name="Target Field",             lat=44.9817, lon=-93.2776,  tz="America/Chicago",    bearing=90,  roof="open",    since=2015, exclude=[], retro=["MIN"], mlbid=142),
    "NYM": dict(name="Citi Field",               lat=40.7571, lon=-73.8458,  tz="America/New_York",   bearing=15,  roof="open",    since=2015, exclude=[], retro=["NYN"], mlbid=121),
    "NYY": dict(name="Yankee Stadium",           lat=40.8296, lon=-73.9262,  tz="America/New_York",   bearing=75,  roof="open",    since=2015, exclude=[], retro=["NYA"], mlbid=147),
    "PHI": dict(name="Citizens Bank Park",       lat=39.9061, lon=-75.1665,  tz="America/New_York",   bearing=10,  roof="open",    since=2015, exclude=[], retro=["PHI"], mlbid=143),
    "PIT": dict(name="PNC Park",                 lat=40.4469, lon=-80.0057,  tz="America/New_York",   bearing=115, roof="open",    since=2015, exclude=[], retro=["PIT"], mlbid=134),
    "SD":  dict(name="Petco Park",               lat=32.7076, lon=-117.1570, tz="America/Los_Angeles",bearing=0,   roof="open",    since=2015, exclude=[], retro=["SDN"], mlbid=135),
    "SEA": dict(name="T-Mobile Park",            lat=47.5914, lon=-122.3325, tz="America/Los_Angeles",bearing=45,  roof="retract", since=2015, exclude=[], retro=["SEA"], mlbid=136),
    "SF":  dict(name="Oracle Park",              lat=37.7786, lon=-122.3893, tz="America/Los_Angeles",bearing=85,  roof="open",    since=2015, exclude=[], retro=["SFN"], mlbid=137),
    "STL": dict(name="Busch Stadium",            lat=38.6226, lon=-90.1928,  tz="America/Chicago",    bearing=60,  roof="open",    since=2015, exclude=[], retro=["SLN"], mlbid=138),
    "TB":  dict(name="Tropicana Field",          lat=27.7683, lon=-82.6534,  tz="America/New_York",   bearing=45,  roof="dome",    since=2015, exclude=[2025], retro=["TBA"], mlbid=139),
    "TEX": dict(name="Globe Life Field",         lat=32.7473, lon=-97.0847,  tz="America/Chicago",    bearing=15,  roof="retract", since=2020, exclude=[], retro=["TEX"], mlbid=140),
    "TOR": dict(name="Rogers Centre",            lat=43.6414, lon=-79.3894,  tz="America/Toronto",    bearing=345, roof="retract", since=2015, exclude=[2020, 2021], retro=["TOR"], mlbid=141),
    "WSH": dict(name="Nationals Park",           lat=38.8730, lon=-77.0074,  tz="America/New_York",   bearing=30,  roof="open",    since=2015, exclude=[], retro=["WAS"], mlbid=120),
}

MLBID_TO_CODE = {v["mlbid"]: k for k, v in PARKS.items()}
RETRO_TO_CODE = {r: k for k, v in PARKS.items() for r in v["retro"]}

# statsapi venue-id -> team code, used to detect games NOT at the home team's
# usual park (neutral sites, temporary venues) so they can be flagged.
def wind_rel_angle(wind_from_deg, bearing):
    """Angle (deg, 0-360) of the direction the wind BLOWS TOWARD, relative to the
    home-plate->CF axis. 0 = straight out to CF, 180 = straight in from CF."""
    return (wind_from_deg + 180.0 - bearing) % 360.0

def wind_sector(rel):
    """'out' | 'in' | 'cross' from a relative blow-toward angle."""
    if rel >= 315 or rel <= 45:
        return "out"
    if 135 <= rel <= 225:
        return "in"
    return "cross"

def wind_label(rel):
    if rel >= 345 or rel <= 15:  return "OUT TO CF"
    if 15 < rel <= 45:           return "OUT TO RF"
    if 315 <= rel < 345:         return "OUT TO LF"
    if 165 <= rel <= 195:        return "IN FROM CF"
    if 135 <= rel < 165:         return "IN FROM RF"
    if 195 < rel <= 225:         return "IN FROM LF"
    if 45 < rel < 135:           return "CROSS L→R"
    return "CROSS R→L"
