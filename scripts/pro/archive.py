"""Shared archive-writing rules for DFSRADAR PRO boards.

The product claim is "every pick archived the moment it posts, graded in
public." That is only true if the archive stops changing once the events it
covers are under way — otherwise a later build can quietly reshuffle a card
after the results are known, and the published record grades something no
subscriber ever saw.

Two shapes, two rules:

  save_locked(path, payload, locked)
      One-shot boards (a night's MLB card, a golf event, a race). Refreshes
      freely until the slate starts; once `locked` is true the first archived
      version is final and later runs leave it alone.

  save_merged(path, payload, key_fields)
      Week-long boards (NFL, CFB), where leans legitimately accumulate as
      kickoffs enter the forecast window. New leans are appended; a lean that
      is already archived is never rewritten or removed, so Sunday's card
      survives Monday's build.
"""
import json, os


def _read(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def save_locked(path, payload, locked, label="archive"):
    """Write unless the slate is under way and a version already exists."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if locked and os.path.exists(path):
        print(f"{label}: locked — keeping the version archived before first start")
        return False
    with open(path, "w") as f:
        json.dump(payload, f, separators=(",", ":"))
    print(f"{label}: wrote {os.path.basename(path)}"
          f"{' (final — slate has started)' if locked else ''}")
    return True


def save_merged(path, payload, key_fields=("game", "k", "who"), label="archive"):
    """Append newly-posted leans to a week's archive; never alter existing ones."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    prev = _read(path)
    if prev and isinstance(prev.get("leans"), list):
        def sig(l):
            return tuple(str(l.get(f) or "") for f in key_fields)
        seen = {sig(l) for l in prev["leans"]}
        added = [l for l in payload.get("leans", []) if sig(l) not in seen]
        merged = prev["leans"] + added
        # keep every game row we have ever archived for this week
        games = {f"{g.get('away')}@{g.get('home')}": g
                 for g in (payload.get("games") or [])}
        for g in prev.get("games") or []:
            games.setdefault(f"{g.get('away')}@{g.get('home')}", g)
        payload = dict(payload, leans=merged, games=list(games.values()))
        print(f"{label}: merged — {len(added)} new lean(s), "
              f"{len(prev['leans'])} preserved")
    with open(path, "w") as f:
        json.dump(payload, f, separators=(",", ":"))
    return True
