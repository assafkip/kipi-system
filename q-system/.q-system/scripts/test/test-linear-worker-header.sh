#!/usr/bin/env bash
# The linear-worker.sh header must describe the merge the script really arms (ASK-4343).
#
# WHY THIS EXISTS
# ---------------
# The header said "It will not MERGE. It opens a PR and stops. Merging is the
# founder's." while arm_automerge() arms GitHub auto-merge on every PR the worker
# opens (ASK-222), and RULE-2026-10-23-A made review and merge Sana's, through the reviewer
# verdict. A header is the first thing a reader trusts; a stale one sent a reader
# to the founder's desk for a merge nobody there performs.
#
# WHAT IT CHECKS
#   1. the header's merge item names a function that is DEFINED in the file
#      (so a rename of arm_automerge turns this red instead of leaving a dead name)
#   2. that item no longer says merging is the founder's
#   3. it names the reviewer verdict the arm waits for, and Sana
# THE NEGATIVE: the same check runs on a copy carrying the old line and must fail.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
WORKER="$HERE/../linear-worker.sh"
fail=0

# check_header <file>: prints the reason and returns 1 when the header is wrong.
check_header() {
  local f="$1" para fn w
  # The merge item: from "will not MERGE" to the next numbered item, header only.
  para="$(sed -n '1,60p' "$f" | awk '/^# *[0-9]\. It will not MERGE/{p=1;print;next} p&&/^# *[0-9]\. /{exit} p{print}')"
  [ -n "$para" ] || { echo "no merge item in header"; return 1; }
  if printf '%s' "$para" | grep -qi "founder's"; then echo "header still says merging is the founder's"; return 1; fi
  fn=""
  for w in $(printf '%s' "$para" | grep -oE '[A-Za-z_]+' | sort -u); do
    if grep -qE "^${w}\(\) *\{" "$f"; then fn="$w"; break; fi
  done
  [ -n "$fn" ] || { echo "header merge item names no function defined in the file"; return 1; }
  printf '%s' "$para" | grep -qi "reviewer" || { echo "header does not name the reviewer verdict"; return 1; }
  # A cited ruling must be a real heading in decisions.md (the first draft cited
  # RULE-2026-11-07-A, a different ruling, and nothing caught it).
  for w in $(printf '%s' "$para" | grep -oE 'RULE-[0-9]{4}-[0-9]{2}-[0-9]{2}-[A-Z]'); do
    grep -qE "^### $w:.*(review|merge)" "$HERE/../../../canonical/decisions.md" || { echo "cited $w is not a review/merge ruling in decisions.md"; return 1; }
  done
  printf '%s' "$para" | grep -q "Sana" || { echo "header does not say merging is Sana's"; return 1; }
  return 0
}

if out="$(check_header "$WORKER")"; then
  echo "PASS header names the merge"
else
  echo "FAIL real header: $out"; fail=1
fi

# Negative self-test on a copy (the pre-fix line); never touches the real file.
tmp="$(mktemp -d)"
{
  printf '#!/usr/bin/env bash\n# 1. It will not MERGE. It opens a PR and stops. Merging is the founder'"'"'s.\n# 2. It will not CLOSE an issue.\n'
  printf 'arm_automerge() {\n  :\n}\n'
} > "$tmp/old.sh"
if check_header "$tmp/old.sh" >/dev/null; then
  echo "FAIL negative: old header passed"; fail=1
else
  echo "PASS old header rejected"
fi
rm "$tmp/old.sh"; rmdir "$tmp"
exit $fail
