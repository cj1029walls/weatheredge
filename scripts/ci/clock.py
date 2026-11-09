#!/usr/bin/env python3
"""The site's clock and watchdog (run by .github/workflows/clock.yml).

Why this exists. GitHub fires this repository's `schedule:` triggers 5-10
hours late (measured Sept-Nov 2026: the 5:23 AM NFL build landed between
11 AM and 3:30 PM ET, and the Sunday "pre-kick" refresh landed after kickoff).
And on Oct 6, 2026 one daily run's deploy job hung in "waiting": it held the
queue for 30 days, every later MLB build was cancelled behind it, the rest of
the postseason was never covered -- and nothing said so.

So the builds no longer depend on *when* GitHub fires them. On every tick --
this workflow's own half-hourly schedule, however late it arrives, or an
outside pinger calling the workflow -- this script:

  1. STARTS WHAT IS DUE. For each workflow in SLOTS it finds the latest slot
     that has passed (Eastern time, so DST needs no edits) and, if no run of
     that workflow has been created since, dispatches one. A late tick costs
     only its own lateness; an on-time pinger makes the builds exact.
  2. UNBLOCKS THE QUEUE. A daily/publish run that has made no progress for
     longer than a healthy run can take is cancelled, so the runs queued
     behind it move again. The tick then fails, on purpose: a red run is the
     email that says it happened.
  3. CHECKS THE RESULTS. Each feed's own timestamp is read from the live
     site; one that is older than its build schedule allows fails the tick,
     and so does a build whose latest run failed. (Runs started here belong
     to github-actions[bot], so GitHub emails nobody about them: this tick's
     red X is that email. At most one alarm every ALARM_EVERY_H hours, so a
     long outage is a few emails, not one every half hour.)

The sport workflows keep one `schedule:` line each as a fallback: if this
clock ever stops, they still run once a day, late.

    python scripts/ci/clock.py             # act
    python scripts/ci/clock.py --dry-run   # print what it would do
    START=pga-weekly.yml python scripts/ci/clock.py   # also start that build now

A build started here asks for its own publish when it finishes (the "Ask for
a publish" step in each sport workflow): GitHub raises no workflow_run event
for a run that github-actions[bot] started, so publish.yml would not hear of it.

Needs `gh` (preinstalled on runners) and GH_TOKEN with actions:write.
No third-party dependencies.
"""
import json, os, subprocess, sys, time, urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
REPO = os.environ.get("GITHUB_REPOSITORY", "cj1029walls/weatheredge")
SITE = os.environ.get("LIVE_SITE", "https://dfsradar.com").rstrip("/")
DRY = "--dry-run" in sys.argv[1:]

EVERY = (0, 1, 2, 3, 4, 5, 6)       # Monday = 0
MON, THU, SAT, SUN = 0, 3, 5, 6

# workflow file -> [(weekdays, "HH:MM" Eastern, hours the slot stays worth running)]
# A slot is "open" from its time until its grace runs out. Each tick looks at
# the workflow's most recent open slot and starts a run unless one has been
# created since that slot's time. Pre-game slots have a short grace: a refresh
# that would land after kickoff is skipped rather than run late.
SLOTS = {
    # MLB slate + PRO card. Off-season these are 30-second "no games" builds.
    "daily.yml": [
        (EVERY, "06:08", 4.4),      # morning slate
        (EVERY, "10:37", 1.4),      # first card with posted prop lines
        (EVERY, "12:07", 4.6),      # before day games
        (EVERY, "16:52", 6.0),      # before night games
    ],
    # MLB prop lines between the daily builds (skipped when a daily build is
    # being started on the same tick: that build refreshes the lines itself).
    "odds-props.yml": [
        (EVERY, "10:12", 0.4),
        (EVERY, "16:23", 0.45),
    ],
    "nfl-weekly.yml": [
        (EVERY, "05:23", 20.0),     # the day's slate
        ((THU,), "18:07", 2.0),     # before Thursday night
        ((SUN,), "11:07", 1.8),     # before the 1 PM kicks
        ((SUN,), "15:07", 1.3),     # before the late window and Sunday night
        ((MON,), "18:07", 2.0),     # before Monday night
    ],
    "cfb-weekly.yml": [
        (EVERY, "05:37", 20.0),
        ((SAT,), "10:22", 1.6),     # before the noon kicks
        ((SAT,), "14:22", 1.1),     # before the 3:30 window
    ],
    "pga-weekly.yml": [(EVERY, "05:52", 20.0)],
    "nascar-weekly.yml": [(EVERY, "06:19", 20.0)],
}
SKIP_IF_STARTING = {"odds-props.yml": "daily.yml"}

# workflow -> minutes without any progress after which a run is stuck.
# daily.yml: build <= 30 min, deploy <= 10, report <= 5. publish.yml: one job,
# 60-minute timeout (it may wait up to 50 for a daily build).
STUCK_MIN = {"daily.yml": 75, "publish.yml": 90}

# live feed -> (timestamp field, max age in hours). Daily builds run 4x between
# 6 AM and 5 PM ET (longest gap 13.3 h); the sport builds run every morning.
FEEDS = {
    "/data.json": ("generated", 17, "daily.yml"), "/pro/data.json": ("generated", 17, "daily.yml"),
    "/nfl/data.json": ("generated", 28, "nfl-weekly.yml"), "/pro/nfl.json": ("updated", 28, "nfl-weekly.yml"),
    "/cfb/data.json": ("generated", 28, "cfb-weekly.yml"), "/pro/cfb.json": ("updated", 28, "cfb-weekly.yml"),
    "/pga/data.json": ("generated", 28, "pga-weekly.yml"), "/pro/pga.json": ("updated", 28, "pga-weekly.yml"),
    "/nascar/data.json": ("generated", 28, "nascar-weekly.yml"), "/pro/nascar.json": ("updated", 28, "nascar-weekly.yml"),
}
ALARM_EVERY_H = 6
# A feed whose build was started within this many minutes is about to change:
# its age is not news yet (this is what keeps a late tick from raising an
# alarm about the very build it is starting).
BUSY_MIN = 150


def note(level, title, msg):
    print(f"::{level} title={title}::{msg}")


def gh(*args, check=True):
    r = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=60)
    if check and r.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:3])}…: {r.stderr.strip()[:200]}")
    return r.stdout


_RUNS = {}


def runs_of(workflow, limit=30):
    """A workflow's latest runs, newest first (one API call per workflow per tick)."""
    if workflow not in _RUNS:
        out = gh("run", "list", "-R", REPO, "--workflow", workflow, "--limit", str(max(limit, 30)),
                 "--json", "databaseId,createdAt,updatedAt,status,conclusion,event")
        _RUNS[workflow] = json.loads(out or "[]")
    return _RUNS[workflow][:limit]


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


# ------------------------------------------------------------ 1. what is due
def open_slot(slots, now_et):
    """The most recent slot that is still open -- (due datetime, hours late) --
    or None. A closed pre-game slot must not hide an older slot that is still
    worth running (the morning build, if nothing has run all day)."""
    best = None
    for back in (0, 1):
        day = (now_et - timedelta(days=back)).date()
        for days, hhmm, grace in slots:
            if day.weekday() not in days:
                continue
            h, m = (int(x) for x in hhmm.split(":"))
            due = datetime(day.year, day.month, day.day, h, m, tzinfo=ET)
            late_h = (now_et - due).total_seconds() / 3600
            if 0 <= late_h <= grace and (best is None or due > best[0]):
                best = (due, late_h)
    return best


def due_now(now_et=None, runs=runs_of):
    """Workflows to start on this tick, in SLOTS order."""
    now_et = now_et or datetime.now(ET)
    start = []
    for wf, slots in SLOTS.items():
        slot = open_slot(slots, now_et)
        if not slot:
            print(f"  {wf}: no slot open")
            continue
        due, late_h = slot
        when = due.strftime("%a %-I:%M %p ET")
        try:
            since = [r for r in runs(wf) if ts(r["createdAt"]) >= due - timedelta(minutes=2)
                     and r.get("conclusion") != "cancelled"]
        except Exception as e:
            note("warning", "clock", f"could not list {wf} runs ({e}) — not starting it blind")
            continue
        if since:
            print(f"  {wf}: {when} slot already has a run ({since[-1]['event']}, "
                  f"{since[-1].get('conclusion') or since[-1]['status']})")
            continue
        start.append((wf, when, late_h))
    names = {w for w, _, _ in start}
    return [(w, when, late) for w, when, late in start
            if not (SKIP_IF_STARTING.get(w) in names)]


def dispatch(wf, when, late_h):
    print(f"  {wf}: {when} slot is due ({late_h * 60:.0f} min ago) — starting it")
    if DRY:
        return True
    try:
        gh("workflow", "run", wf, "-R", REPO, "--ref", "main")
        time.sleep(2)
        return True
    except Exception as e:
        note("warning", "clock", f"could not start {wf}: {e}")
        return False


# ------------------------------------------------------------ 2. stuck runs
def unblock(now=None, runs=runs_of):
    """Cancel runs that stopped making progress. Returns what was cancelled."""
    now = now or datetime.now(timezone.utc)
    cancelled = []
    for wf, limit in STUCK_MIN.items():
        try:
            open_ = [r for r in runs(wf, 20) if r["status"] != "completed"]
        except Exception as e:
            note("warning", "clock", f"could not list {wf} runs ({e})")
            continue
        if not open_:
            continue
        # Only the oldest open run can be the one holding the queue; the ones
        # behind it are waiting their turn and start as soon as it is gone.
        r = min(open_, key=lambda x: ts(x["createdAt"]))
        idle = (now - ts(r.get("updatedAt") or r["createdAt"])).total_seconds() / 60
        age = (now - ts(r["createdAt"])).total_seconds() / 60
        if idle <= limit or age <= limit:
            continue
        url = f"https://github.com/{REPO}/actions/runs/{r['databaseId']}"
        print(f"  {wf}: run {r['databaseId']} ({r['status']}) has made no progress for "
              f"{idle / 60:.1f} h — cancelling it so the queue moves")
        if not DRY:
            try:
                gh("run", "cancel", str(r["databaseId"]), "-R", REPO)
            except Exception as e:
                note("warning", "clock", f"could not cancel {url}: {e}")
                continue
        cancelled.append(f"{wf} run {r['databaseId']} (no progress for {idle / 60:.1f} h) {url}")
    return cancelled


# ------------------------------------------------------------ 3. live feeds
def built_at(stamp):
    """'2026-11-09 15:38 ET' -> aware datetime (None if it isn't one)."""
    try:
        return datetime.strptime(str(stamp).replace(" ET", ""), "%Y-%m-%d %H:%M").replace(tzinfo=ET)
    except ValueError:
        return None


def fetch_feed(path):
    url = f"{SITE}{path}?clock={int(time.time())}"
    req = urllib.request.Request(url, headers={"User-Agent": "dfsradar-clock/1.0",
                                               "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def in_flight(wf, started=(), now=None, runs=runs_of):
    """Was wf started on this tick, or in the last BUSY_MIN minutes?"""
    if wf in started:
        return True
    now = now or datetime.now(timezone.utc)
    try:
        return any(r.get("conclusion") not in ("cancelled", "failure")
                   and (now - ts(r["createdAt"])).total_seconds() < BUSY_MIN * 60
                   for r in runs(wf))
    except Exception:
        return False


def stale_feeds(now_et=None, fetch=fetch_feed, busy=lambda wf: False):
    now_et = now_et or datetime.now(ET)
    old = []
    for path, (field, max_h, wf) in FEEDS.items():
        try:
            when = built_at(fetch(path).get(field))
        except Exception as e:
            print(f"  {path}: could not be read ({str(e)[:80]}) — skipped this tick")
            continue
        if when is None:
            continue
        age = (now_et - when).total_seconds() / 3600
        if age > max_h and busy(wf):
            print(f"  {path}: {age:.0f} h old, and its build is running — not an alarm yet")
        elif age > max_h:
            old.append(f"{path} was last built {age:.0f} h ago (limit {max_h} h)")
    return old


def failed_builds(now=None, runs=runs_of):
    """Builds whose latest finished run failed within the last day."""
    now = now or datetime.now(timezone.utc)
    bad = []
    for wf in list(SLOTS) + ["publish.yml"]:
        try:
            done = [r for r in runs(wf) if r["status"] == "completed"
                    and r.get("conclusion") not in ("cancelled", "skipped")]
        except Exception:
            continue
        if not done:
            continue
        last = max(done, key=lambda r: ts(r["createdAt"]))
        if last.get("conclusion") == "failure" and (now - ts(last["createdAt"])).total_seconds() < 86400:
            bad.append(f"{wf}: its latest run failed — https://github.com/{REPO}/actions/runs/{last['databaseId']}")
    return bad


def alarmed_recently(runs=runs_of, now=None):
    now = now or datetime.now(timezone.utc)
    try:
        return any(r.get("conclusion") == "failure"
                   and (now - ts(r["createdAt"])).total_seconds() < ALARM_EVERY_H * 3600
                   for r in runs("clock.yml", 40))
    except Exception:
        return False


def main():
    now_et = datetime.now(ET)
    print(f"tick {now_et.strftime('%a %b %-d %-I:%M %p ET')}" + (" (dry run)" if DRY else ""))
    fail = []

    print("stuck runs:")
    try:
        gone = unblock()
    except Exception as e:
        gone = []
        note("warning", "clock", f"stuck-run check failed ({e})")
    for g in gone:
        note("error", "Cancelled a stuck run", g + " — the builds queued behind it can run again")
    fail += gone

    print("due builds:")
    try:
        todo = due_now(now_et)
    except Exception as e:
        todo = []
        note("warning", "clock", f"schedule check failed ({e})")
    started = [wf for wf, when, late in todo if dispatch(wf, when, late)]
    if not todo:
        print("  nothing to start")
    asked = os.environ.get("START", "").strip()
    if asked in SLOTS and asked not in started:
        if dispatch(asked, "on request", 0):
            started.append(asked)
    elif asked and asked not in SLOTS:
        note("warning", "clock", f"START={asked!r} is not a build this clock runs ({', '.join(SLOTS)})")

    print("results:")
    try:
        old = stale_feeds(now_et, busy=lambda wf: in_flight(wf, started))
    except Exception as e:
        old = []
        note("warning", "clock", f"feed check failed ({e})")
    old = [o + " — its build is not landing; see that workflow's runs" for o in old]
    try:
        old += failed_builds()
    except Exception as e:
        note("warning", "clock", f"build check failed ({e})")
    if old:
        again = alarmed_recently()
        for o in old:
            note("warning" if again else "error", "Still not right" if again else "Needs a look", o)
        if not again:
            fail += old
    else:
        print("  every feed is current and every build's latest run passed")

    summ = os.environ.get("GITHUB_STEP_SUMMARY")
    if summ:
        with open(summ, "a") as f:
            f.write(f"- tick {now_et.strftime('%a %-I:%M %p ET')}: started {', '.join(started) or 'nothing'}"
                    f"{'; cancelled ' + str(len(gone)) + ' stuck run(s)' if gone else ''}"
                    f"{'; ' + str(len(old)) + ' feed(s) or build(s) need a look' if old else ''}\n")
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
