#!/usr/bin/env bash
# Scar (2026-07-02, sp-cd530cc7): on block, the guard exited 2 but printed its
# message as JSON to STDOUT. Claude Code feeds only STDERR back to the model on
# exit 2, so every block surfaced as "No stderr output" — a silent wall. The
# exit-code contract (skill-hook-pairing.md): exit 2 = block, message on stderr.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
GUARD="$REPO_ROOT/q-system/.q-system/scripts/prompt-only-enforcement-guard.py"
FIXTURE="$(mktemp -d)"
trap 'python3 -c "import shutil,sys; shutil.rmtree(sys.argv[1], ignore_errors=True)" "$FIXTURE"' EXIT

# A prompt-only enforcement claim with no executable blocker named must block.
printf 'This rule is enforced by the skill.\n' > "$FIXTURE/violation.md"

set +e
OUT="$(python3 "$GUARD" "$FIXTURE/violation.md" 2>/dev/null)"
ERR="$(python3 "$GUARD" "$FIXTURE/violation.md" 2>&1 >/dev/null)"
CODE=$?
set -e

[ "$CODE" -eq 2 ] || { echo "FAIL: violation exited $CODE, want 2"; exit 1; }
case "$ERR" in
  *"BLOCK: prompt-only enforcement"*) ;;
  *) echo "FAIL: block message missing from STDERR (Claude sees 'No stderr output'): '$ERR'"; exit 1;;
esac
[ -z "$OUT" ] || { echo "FAIL: block message leaked to STDOUT: '$OUT'"; exit 1; }
echo "ok: block message goes to stderr, stdout stays clean"

# A clean file passes silently.
printf 'The lint hook blocks this at write time.\n' > "$FIXTURE/clean.md"
python3 "$GUARD" "$FIXTURE/clean.md" || { echo "FAIL: clean file blocked"; exit 1; }
echo "ok: clean file passes"

echo "PASS: prompt-only-enforcement-guard stderr contract"
