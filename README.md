# DFSRADAR

Weather, venue and umpire edges for MLB, NFL, CFB, PGA and NASCAR — live at
[dfsradar.com](https://dfsradar.com). The radars are free; the PRO desks add the
player-level boards on top, and every call is graded in public. Part of the DFS Kitchen family.

*Scan the slate. Find the edge.*

| Path | What it is |
|---|---|
| `/` | The landing page |
| `/mlb/` `/nfl/` `/cfb/` `/pga/` `/nascar/` | The free radars: each venue's forecast, measured against that venue's own history |
| `/pro/` | The PRO desks (DFSRADAR PRO or DFS Kitchen All-Access members) |
| `/record/` | The public record: every graded call, wins and losses, and the MLB calibration table |

Static GitHub Pages. Each page inlines its own CSS and JS; `site/assets/fresh.js` is the
shared "updated / last slate" chip.

## How the data is built

Scheduled GitHub Actions rebuild each sport's JSON from free sources (Open-Meteo forecasts,
the leagues' public schedules and box scores), grade the calls whose games are final, and redeploy:

- **`daily.yml`** — MLB, four times a day (~6:08 AM, 10:37 AM, 12:07 PM, 4:52 PM ET). Builds
  `site/data.json`, grades the free radar's calls (`data/accuracy.json`), grades the PRO card
  (`scripts/pro/grade.py` → `site/pro/record.json`) and builds the PRO board. These MLB files are
  deployed but not committed.
- **`nfl-weekly.yml`, `cfb-weekly.yml`, `pga-weekly.yml`, `nascar-weekly.yml`** — daily: the free
  slate, the PRO board and its grader (`site/pro/<sport>_record.json`).
- **`publish.yml`** — redeploys after a sport workflow commits, carrying the live MLB files forward.

Needs two repository secrets: `ODDS_API_KEY` and `CFBD_API_KEY`.

### The MLB radar

1. **Historical layer** (`data/parks_history.json`, rebuilt each January): [Retrosheet](https://www.retrosheet.org)
   game logs since 2015, park-filtered to each team's current stadium, joined to hourly weather
   from the [Open-Meteo archive](https://open-meteo.com).
2. **Daily layer**: today's schedule and first-pitch forecasts, matched against that park's
   history — ±6°F, ±6 mph, the same wind sector relative to the park's orientation, dew point
   on the tightest pass; the window widens until at least 12 games match.

O/U rates come from real final scores (era-adjusted) against today's total. Totals come from the
odds feed; pin one in `data/lines.json` (`{"WSH@CHC": 9.0}`) to override it. A game with no line
uses the matched-sample median, flagged as an estimate.

## Setup (one time)

1. Push this repo to GitHub; **Settings → Pages → Source: GitHub Actions**.
2. Add the `ODDS_API_KEY` and `CFBD_API_KEY` secrets.
3. Run the history workflows once: **Build history dataset**, **Build hitter history**,
   **Build NFL history**, **Build CFB history**.
4. Run **Daily slate build & deploy**. Everything then runs on its schedule.

## Honest limitations (MLB radar)

- **Retractable roofs**: Retrosheet doesn't record roof state, so today's roof is a heuristic
  (closed at ≥95°F, ≤48°F, or rain risk ≥45%), labelled as such.
- **Historical first-pitch weather**: game logs carry day/night only, so history is sampled at
  1 PM / 7 PM local.
- **Park orientations** are curated approximations (±10–15°); wind sectors are 90° wide so small
  errors don't change the bucket.
- **Venue changes**: Toronto 2020–21 and Tampa Bay 2025 home games are excluded (wrong venues);
  Atlanta's history starts 2017, Texas 2020 and the Athletics 2025 (new parks).
- The current season joins the history layer in the offseason, when Retrosheet publishes it.

## Local development

```
python scripts/daily_build.py --offline   # builds site/data.json from tests/fixtures
cd site && python -m http.server          # open http://localhost:8000
```

The offline build also writes `data/predictions/<date>.json` and copies `data/accuracy.json` to
`site/accuracy.json` — run it in a scratch copy to keep the tree clean. The MLB radar falls back
to embedded sample data when `data.json` is missing; `/record/` shows "No graded nights yet" for
the MLB PRO desk until `site/pro/record.json` exists.
