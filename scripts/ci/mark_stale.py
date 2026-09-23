#!/usr/bin/env python3
"""Mark a published JSON feed as NOT refreshed, keeping its last good content.

    python scripts/ci/mark_stale.py <file.json> "<reason>"

The workflows call this when a builder step fails, so the page says so instead
of passing old data off as current. It adds

    "stale": true,
    "status": {"ok": false, "stale": true, "reason": ..., "lastGood": ...,
               "checked": ..., "run": ...}

and prefixes the text each page already renders -- "brief" on the free pages,
"note" on the PRO boards -- with "⚠ Not refreshed since <lastGood> — <reason>."
so no page change is needed for readers to see it.

Repeated failures keep the first lastGood and the original text (no stacked
prefixes). If the builder already marked the file itself in this same run
(status.run == GITHUB_RUN_ID) its more specific reason is kept. The next
successful build rewrites the file from scratch, which clears the marker.
Never fails the job: a file it cannot read is reported and skipped.
"""
import json, os, sys
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def mark(path, reason):
    try:
        with open(path) as f:
            data = json.load(f)
    except Exception as e:
        print(f"::warning title=mark_stale::cannot mark {path} ({e}) — nothing to mark")
        return False
    if not isinstance(data, dict):
        print(f"::warning title=mark_stale::{path} is not a JSON object — not marked")
        return False
    run = os.environ.get("GITHUB_RUN_ID")
    prev = data.get("status") if isinstance(data.get("status"), dict) else {}
    if prev.get("ok") is False and run and prev.get("run") == run:
        print(f"{path}: already marked stale by its builder this run — keeping its reason")
        return True
    field = "brief" if "brief" in data else "note"
    was_stale = prev.get("ok") is False
    last_good = (prev.get("lastGood") if was_stale else None) or \
        data.get("generated") or data.get("updated") or data.get("built")
    orig = prev.get("orig") if was_stale and "orig" in prev else data.get(field)
    reason = reason.strip().rstrip(".")
    data["stale"] = True
    data["status"] = dict(ok=False, stale=True, reason=reason, lastGood=last_good,
                          checked=datetime.now(ET).strftime("%Y-%m-%d %H:%M ET"),
                          run=run, orig=orig)
    since = f" since {last_good}" if last_good else ""
    data[field] = f"⚠ Not refreshed{since} — {reason}." + (f" {orig}" if orig else "")
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, separators=(",", ":"), ensure_ascii=False)
    os.replace(tmp, path)
    print(f"::warning file={path},title=Marked stale::{path} kept from {last_good or 'an earlier run'} — {reason}")
    return True


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: mark_stale.py <file.json> <reason>")
    mark(sys.argv[1], sys.argv[2])
