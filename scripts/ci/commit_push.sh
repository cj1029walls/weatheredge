#!/usr/bin/env bash
# Commit the given outputs (if they changed) and push them to main, safely.
#
#   bash scripts/ci/commit_push.sh "<commit message>" <path> [<path> ...]
#
# Replaces the per-workflow "git add a b c 2>/dev/null || true; git commit ||
# echo; git pull --rebase; git push" blocks, which lost data silently:
#   * one missing pathspec makes `git add` stage NOTHING (exit 128, masked by
#     `|| true`), so the commit then says "no changes" and the run stays green;
#   * `git pull --rebase` without --autostash refuses a dirty tree, and a
#     content conflict (site/pro/props.json is written by BOTH daily.yml and
#     odds-props.yml) leaves the repo mid-rebase, so every later attempt fails
#     too ("Pulling is not possible because you have unmerged files");
#   * the sport/history workflows never retried a push that lost the race.
#
# Here: a missing path is warned about and skipped (prefix it with "?" when it
# may legitimately not exist yet); everything else is staged; the commit is
# rebased onto the latest main with -X theirs -- these are generated files, so
# on a same-file conflict the copy this run just built wins; a failed rebase is
# aborted before the next attempt; five attempts with backoff; ::error:: and a
# non-zero exit if the push never lands.
set -uo pipefail
msg="${1:?usage: commit_push.sh <message> <path>...}"; shift
git config user.name "weatheredge-bot"
git config user.email "actions@users.noreply.github.com"

paths=()
for p in "$@"; do
  optional=0
  case "$p" in \?*) optional=1; p="${p#\?}" ;; esac
  if [ -e "$p" ]; then
    paths+=("$p")
  elif [ "$optional" = 0 ]; then
    echo "::warning title=commit: missing output::$p does not exist — not committed (did the step that writes it fail?)"
  fi
done
if [ ${#paths[@]} -eq 0 ]; then
  echo "::warning title=commit::nothing to stage for '$msg'"
  exit 0
fi

git add -A -- "${paths[@]}" || { echo "::error title=commit::git add failed for '$msg'"; exit 1; }
if git diff --cached --quiet; then
  echo "no changes to commit"
  exit 0
fi
git commit -q -m "$msg" || { echo "::error title=commit::git commit failed for '$msg'"; exit 1; }

for i in 1 2 3 4 5; do
  if git fetch -q origin main && git rebase -q --autostash -X theirs origin/main; then
    if git push -q origin HEAD:main; then
      echo "pushed '$msg' (attempt $i)"
      exit 0
    fi
  else
    git rebase --abort >/dev/null 2>&1 || true
  fi
  echo "push attempt $i failed — retrying"
  sleep $((i * 7))
done
echo "::error title=commit: NOT saved::'$msg' could not be pushed after 5 attempts — this run's data was not saved"
exit 1
