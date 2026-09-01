#!/bin/bash
# friction-note.sh -- append ONE friction line to this instance's friction ledger.
#
# The artifact half of plan item 2b (prd-morning-brief-learns-2026-09-01). Per
# the lesson feedback-lands-where-artifacts-exist, a concern with no file cannot
# absorb a fix; it lands in the nearest editable layer instead. This file is the
# artifact. weekly-improve.py is its consumer; nothing else reads it.
#
# Refuses, exit 1, on:
#   - an email address in the line (Codex finding-18: friction can carry client
#     data, and the weekly proposal is delivered to Slack)
#   - a roadmap or unknown verdict from roadmap_scope.py (Codex finding-1: the
#     declared --target alone was a bypass; the text is classified too, and
#     unknown is a refusal, never a pass)
#
# Writes to THIS instance's q-system/memory/friction.jsonl (instance-owned under
# kipi update, so lines survive fan-out) and creates it on a fresh instance: the
# script fans out to every instance, the file does not.
#
# Usage: friction-note.sh "<text>" --target <rule|lint|hook|trigger|context|skill|prompt|test|script|job|plist|docs|gate|brief>
# Env:   KIPI_FRICTION_FILE overrides the ledger path (tests use a temp file).
set -euo pipefail
SCRIPTS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
QROOT="$(cd "$SCRIPTS/../.." && pwd)"   # scripts -> .q-system -> q-system
FILE="${KIPI_FRICTION_FILE:-$QROOT/memory/friction.jsonl}"

TEXT=""; TARGET=""
while [ $# -gt 0 ]; do
  case "$1" in
    --target) TARGET="${2:-}"; shift 2 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) TEXT="$1"; shift ;;
  esac
done
[ -n "$TEXT" ] || { echo "usage: friction-note.sh \"<text>\" --target <target>" >&2; exit 1; }
[ -n "$TARGET" ] || { echo "refused: --target is required (unknown is a refusal)" >&2; exit 1; }

if printf '%s' "$TEXT" | grep -Eq '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'; then
  echo "refused: a friction line must not carry an email address (it is delivered to Slack)" >&2
  exit 1
fi

set +e
VERDICT="$(python3 "$SCRIPTS/roadmap_scope.py" --target "$TARGET" "$TEXT")"
RC=$?
set -e
if [ "$RC" -ne 0 ]; then
  echo "refused: roadmap_scope verdict is not system: $VERDICT" >&2
  exit 1
fi

mkdir -p "$(dirname "$FILE")"
# The id is allocated and the row appended inside ONE exclusive lock, and the
# suffix is max(existing)+1, never a line count (both Codex reviewers of this
# issue, 2026-09-01: a count re-issues an id after a gap, and two writers that
# both count before either appends mint the same id; the id is the citation
# key the weekly proposal uses, so a duplicate breaks traceability).
KIPI_FRICTION_TARGET="$TARGET" KIPI_FRICTION_TEXT="$TEXT" \
python3 - "$FILE" <<'PY'
import datetime as dt, fcntl, json, os, re, sys
path = sys.argv[1]
today = dt.date.today().isoformat()
pat = re.compile(r'"id": "fr-' + re.escape(today) + r'-(\d+)"')
with open(path, "a+", encoding="utf-8") as fh:
    fcntl.flock(fh, fcntl.LOCK_EX)
    fh.seek(0)
    used = [int(m.group(1)) for m in pat.finditer(fh.read())]
    ident = f"fr-{today}-{(max(used) + 1) if used else 1:02d}"
    row = {"id": ident,
           "at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
           "target": os.environ["KIPI_FRICTION_TARGET"],
           "text": os.environ["KIPI_FRICTION_TEXT"],
           "verdict": "system"}
    fh.seek(0, 2)
    fh.write(json.dumps(row) + "\n")
    fh.flush()
    fcntl.flock(fh, fcntl.LOCK_UN)
print(f"wrote friction line {ident} to {path}")
PY
