#!/usr/bin/env bash
# Last step of a job: turn step outcomes into annotations, a summary table and
# (for page builders) a red run, so a failure can't hide behind `|| echo`.
#
#   bash scripts/ci/gate.sh [--output NAME] "Label=<outcome>" ... [-- "Label=<outcome>" ...]
#
# Before "--": steps whose failure means a page was NOT refreshed. Each failure
#   -> ::error:: and exit 1 (the run goes red; GitHub emails the owner).
# After "--": best-effort steps (graders, history refreshers, carry-forward).
#   Each failure -> ::warning:: only.
# --output NAME: also write the failed labels (comma-separated) to
#   $GITHUB_OUTPUT as NAME, for a later job to act on (daily.yml fails its
#   run only AFTER it has deployed).
# Outcomes come from ${{ steps.<id>.outcome }} of continue-on-error steps.
set -u
out=""
if [ "${1:-}" = "--output" ]; then out="$2"; shift 2; fi
summary="${GITHUB_STEP_SUMMARY:-/dev/null}"
{ echo; echo "| step | outcome |"; echo "|---|---|"; } >> "$summary"
critical=1; fail=0; failed=()
for a in "$@"; do
  if [ "$a" = "--" ]; then critical=0; continue; fi
  label="${a%=*}"; outcome="${a##*=}"
  echo "| $label | ${outcome:-not run} |" >> "$summary"
  [ "$outcome" = "failure" ] || continue
  failed+=("$label")
  if [ "$critical" = 1 ]; then
    echo "::error title=$label NOT refreshed::$label failed — the page keeps its last good data, marked stale. See that step's log."
    fail=1
  else
    echo "::warning title=$label failed::$label failed — its output is the last good copy; it retries next run. See that step's log."
  fi
done
if [ -n "$out" ] && [ -n "${GITHUB_OUTPUT:-}" ]; then
  (IFS=','; echo "$out=${failed[*]:-}") >> "$GITHUB_OUTPUT"
fi
exit "$fail"
