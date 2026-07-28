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
  "BLOCK: prompt-only enforcement"*) ;;  # plain text, not {"message": ...} JSON
  *) echo "FAIL: STDERR must START with the plain-text BLOCK line (Codex finding: JSON-on-stderr would pass a contains-check): '$ERR'"; exit 1;;
esac
[ -z "$OUT" ] || { echo "FAIL: block message leaked to STDOUT: '$OUT'"; exit 1; }
echo "ok: block message goes to stderr as plain text, stdout stays clean"

# Hook entrypoint: Claude Code invokes with NO argv and the PostToolUse payload
# on stdin (Codex finding: an argv-only test would miss a stdin-path regression
# back to stdout JSON).
set +e
HOOK_OUT="$(printf '{"session_id":"t","hook_event_name":"PostToolUse","tool_name":"Write","tool_input":{"file_path":"%s"}}' "$FIXTURE/violation.md" | python3 "$GUARD" 2>/dev/null)"
HOOK_ERR="$(printf '{"session_id":"t","hook_event_name":"PostToolUse","tool_name":"Write","tool_input":{"file_path":"%s"}}' "$FIXTURE/violation.md" | python3 "$GUARD" 2>&1 >/dev/null)"
HOOK_CODE=$?
set -e
[ "$HOOK_CODE" -eq 2 ] || { echo "FAIL: stdin hook mode exited $HOOK_CODE, want 2"; exit 1; }
case "$HOOK_ERR" in
  "BLOCK: prompt-only enforcement"*) ;;
  *) echo "FAIL: stdin hook mode lost the plain-text stderr message: '$HOOK_ERR'"; exit 1;;
esac
[ -z "$HOOK_OUT" ] || { echo "FAIL: stdin hook mode leaked to STDOUT: '$HOOK_OUT'"; exit 1; }
echo "ok: stdin hook entrypoint blocks on stderr too"

# A clean file passes silently.
printf 'The lint hook blocks this at write time.\n' > "$FIXTURE/clean.md"
python3 "$GUARD" "$FIXTURE/clean.md" || { echo "FAIL: clean file blocked"; exit 1; }
echo "ok: clean file passes"

echo "PASS: prompt-only-enforcement-guard stderr contract"
