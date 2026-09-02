#!/usr/bin/env bash
# Report what changed in upstream FluidVoice (macOS) since the tracked baseline.
# Read-only: fetches upstream refs/tags, prints a triage report, touches nothing.
# After triaging, record the result in docs/UPSTREAM-TRACKING.md and bump the
# baseline in docs/upstream-baseline.txt (both, in the same commit).
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

baseline_file=docs/upstream-baseline.txt
[ -f "$baseline_file" ] || { echo "error: $baseline_file not found" >&2; exit 1; }
base_sha="$(sed -n 's/^sha=//p' "$baseline_file")"
base_tag="$(sed -n 's/^tag=//p' "$baseline_file")"
base_date="$(sed -n 's/^date=//p' "$baseline_file")"
[ -n "$base_sha" ] && [ -n "$base_date" ] || { echo "error: $baseline_file is missing sha=/date=" >&2; exit 1; }

remote="$(git remote | grep -x upstream || true)"
[ -n "$remote" ] || { echo "error: no 'upstream' git remote (add: git remote add upstream https://github.com/altic-dev/FluidVoice.git)" >&2; exit 1; }

echo "== fetching upstream (altic-dev/FluidVoice) =="
git fetch upstream --tags --quiet

tip="$(git rev-parse upstream/main)"
if [ "$base_sha" = "$tip" ]; then
    echo "Up to date: upstream/main == tracked baseline ${base_sha:0:7} ($base_tag, $base_date)."
    exit 0
fi

echo "== upstream moved: ${base_sha:0:7}..${tip:0:7} — $(git rev-list --count "$base_sha..upstream/main") commits =="

echo
echo "-- new tags since baseline --"
git for-each-ref --merged upstream/main --sort=creatordate \
    --format='%(refname:short)|%(creatordate:short)' refs/tags \
    | awk -F'|' -v d="$base_date" '$2 > d {print "  " $1 " (" $2 ")"}'

echo
echo "-- commits (no merges), newest first --"
git log --no-merges --format='  %h %ad %s' --date=short "$base_sha..upstream/main"

echo
echo "-- Swift sources touched that map to ported behavior --"
git diff --name-only "$base_sha..upstream/main" -- 'Sources/*.swift' \
    | grep -iE 'prompt|punctuat|rule|overlay|hotkey|insert|pasting|spoken|dictation|settings' \
    || echo "  (none of the watched areas changed)"

echo
echo "Next: triage the above in docs/UPSTREAM-TRACKING.md (status per change),"
echo "then update docs/upstream-baseline.txt: sha=$tip short=${tip:0:7} date=<commit date> tag=<newest tag> checked=<today>."
