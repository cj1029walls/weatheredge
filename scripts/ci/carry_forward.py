#!/usr/bin/env python3
"""Carry forward the live copies of the MLB files daily.yml builds but never commits.

    python scripts/ci/carry_forward.py             # all six, overwrite  (publish.yml)
    python scripts/ci/carry_forward.py --missing   # only files this run lacks (daily.yml)

daily.yml writes site/data.json, site/accuracy.json, site/teaser.json and
site/pro/{data,record,umps}.json and deploys them without committing them (they
are gitignored or untracked). Any deploy that did not build them -- publish.yml,
or a daily run in which grading/umps/PRO failed -- would otherwise publish a
site WITHOUT them: 404s on the MLB pages.

Each file is fetched from <LIVE_SITE>/<path>?v=<unique> (the query string makes
the Pages CDN go back to origin) and must be HTTP 200, parse as a JSON object
and carry its expected top-level key, so an HTML error page or a truncated
body is rejected rather than published.

Default mode: any failure -> ::error:: and exit 1, so the caller does NOT deploy
(we never publish a site missing MLB data). --missing mode: failures are
warnings (the fresh MLB slate from this run is still worth deploying).
"""
import json, os, sys, time, urllib.request

BASE = os.environ.get("LIVE_SITE", "https://dfsradar.com").rstrip("/")
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SITE = os.path.join(ROOT, "site")
FILES = {                       # site-relative path -> top-level key it must have
    "data.json": "games",
    "accuracy.json": "days",
    "teaser.json": "counts",
    "pro/data.json": "targets",
    "pro/record.json": "summary",
    "pro/umps.json": "umps",
}


def fetch(path):
    url = f"{BASE}/{path}?v={int(time.time())}-{os.environ.get('GITHUB_RUN_ID', 'local')}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "dfsradar-publish/1.0", "Cache-Control": "no-cache", "Pragma": "no-cache"})
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                if r.status != 200:
                    raise ValueError(f"HTTP {r.status}")
                body = r.read()
            data = json.loads(body)
            if not isinstance(data, dict) or FILES[path] not in data:
                raise ValueError(f"not the expected JSON (no '{FILES[path]}' key)")
            return body, data
        except Exception as e:          # includes HTTPError 404/5xx and JSON errors
            last = e
            time.sleep(4 * (attempt + 1))
    raise RuntimeError(f"{url}: {last}")


def main():
    only_missing = "--missing" in sys.argv[1:]
    failed = []
    for path in FILES:
        dest = os.path.join(SITE, path)
        if only_missing and os.path.exists(dest):
            continue
        try:
            body, data = fetch(path)
        except Exception as e:
            failed.append(path)
            level = "warning" if only_missing else "error"
            print(f"::{level} title=carry-forward failed::site/{path}: {e}")
            continue
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest + ".tmp", "wb") as f:
            f.write(body)
        os.replace(dest + ".tmp", dest)
        stamp = data.get("generated") or data.get("updated") or data.get("built") or "?"
        print(f"carried forward site/{path} ({len(body):,} bytes, built {stamp})")
    if failed and not only_missing:
        print(f"::error title=Deploy aborted::{len(failed)} live file(s) unavailable "
              f"({', '.join(failed)}) — not publishing a site without MLB data")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
