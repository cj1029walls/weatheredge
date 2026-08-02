# DFS Radar

MLB weather edges for DFS — live at [dfsradar.com](https://dfsradar.com). Not a model, not a simulation — real data for a real edge. Part of the DFS Kitchen product family.

For every game on today's slate, the site shows the first-pitch forecast at that park
and what **actually happened** in historically similar weather at the same park since
2019: home runs, runs, strikeouts, and over/under rates against today's total.

## How it works

Two data layers, both free:

1. **Historical layer** (`data/parks_history.json`, rebuilt yearly):
   [Retrosheet](https://www.retrosheet.org) game logs (runs / HR / K per game, park-filtered
   to each team's current stadium) joined to hourly historical weather from the
   [Open-Meteo archive](https://open-meteo.com). ~13,000 games.
2. **Daily layer** (`site/data.json`, rebuilt 3× daily by GitHub Actions):
   today's schedule from the MLB Stats API + first-pitch forecasts from Open-Meteo,
   matched against the historical layer (±6°F, wind speed ±6 mph, same wind sector
   relative to each park's orientation — window widens adaptively to keep ≥12 games).

O/U rates are computed from real final scores against today's total, so they update
if the line moves. Pin real book totals in `data/lines.json` (`{"WSH@CHC": 9.0}`);
otherwise the matched-sample median is used and flagged as an estimate.

## Setup (one time, ~10 minutes)

1. Create a new GitHub repository (public, or private with Pages enabled) and push
   this folder to it.
2. In the repo: **Settings → Pages → Source: GitHub Actions**.
3. **Actions tab → "Build history dataset" → Run workflow.** Takes ~10-20 min;
   commits `data/parks_history.json`.
4. **Actions tab → "Daily slate build & deploy" → Run workflow.** Builds today's
   slate and deploys the site. After this, it runs automatically at ~6 AM,
   ~12:30 PM, and ~5 PM ET every day.
5. Your site is live at `https://<your-username>.github.io/<repo-name>/`.
   Add a custom domain in Settings → Pages whenever you're ready.

## Honest limitations (v1)

- **Retractable roofs**: Retrosheet doesn't record roof state, so history for
  retractable parks mixes open/closed games; today's roof state is a heuristic
  (closed if ≥95°F, ≤48°F, or high rain risk), labeled as such.
- **First-pitch weather (historical)**: game logs carry day/night only, so
  historical weather is sampled at 1 PM / 7 PM local.
- **Park orientations** are curated approximations (±10-15°); wind sectors are
  90° wide so small errors don't change the bucket.
- **2020 & relocation seasons**: Toronto 2020-21 and Tampa Bay 2025 home games are
  excluded (wrong venues); Texas history starts 2020 (new park), Athletics 2025.
- The current season's completed games are not yet in the history layer (Retrosheet
  publishes each season in the offseason; the January workflow picks it up).

## Local development

```
python scripts/daily_build.py --offline   # builds site/data.json from tests/fixtures
cd site && python -m http.server          # open http://localhost:8000
```

The site renders with embedded sample data whenever `data.json` is missing, so the
design can be iterated without the pipeline.
