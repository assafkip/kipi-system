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

# --- mention-vs-claim FP (sp-edf9395d, 2026-07-02) ---
# Scar: the guard flagged 11 lines of the PRD documenting the guard itself,
# including pure frontmatter (id:/title:/status:), because the deterministic
# suppressors read the same +/-2-line window as the trigger regexes. A doc
# that names its executable blocker a few lines from the claim-shaped
# sentence was indistinguishable from a prompt-only claim.

# YAML frontmatter metadata is a description, not an enforcement claim.
# (Modeled on prd-prompt-only-guard-stderr-2026-07-02: "Prompt Only Guard"
# in a title matches subject "prompt" + action "guard".)
cat > "$FIXTURE/frontmatter.md" <<'EOF'
---
id: prd-prompt-only-guard-stderr-2026-07-02
title: Prompt Only Guard Stderr
status: archived
---

Body text with no claim-shaped sentences at all.
EOF
python3 "$GUARD" "$FIXTURE/frontmatter.md" \
  || { echo "FAIL: frontmatter metadata flagged as an enforcement claim (sp-edf9395d)"; exit 1; }
echo "ok: frontmatter metadata passes"

# An executable blocker named within the suppressor window (4 lines from the
# claim-shaped sentence, outside the +/-2 trigger window) is a MENTION.
cat > "$FIXTURE/nearby-blocker.md" <<'EOF'
The skill blocks low-quality drafts before they ship.
Detail line one about what counts as low quality.
Detail line two about the draft flow.
Detail line three about ownership.
Enforcement is voice-lint.py, wired as a PostToolUse hook.
EOF
python3 "$GUARD" "$FIXTURE/nearby-blocker.md" \
  || { echo "FAIL: blocker named 4 lines away still flagged (sp-edf9395d)"; exit 1; }
echo "ok: blocker named within 6 lines suppresses"

# The suppressor window is wider, NOT document-wide: a blocker named 8 lines
# away does not license a claim.
cat > "$FIXTURE/distant-blocker.md" <<'EOF'
This rule is enforced by the skill.
filler line 1
filler line 2
filler line 3
filler line 4
filler line 5
filler line 6
filler line 7
The voice-lint.py PostToolUse hook lives elsewhere in this doc.
EOF
set +e
python3 "$GUARD" "$FIXTURE/distant-blocker.md" 2>/dev/null
DISTANT_CODE=$?
set -e
[ "$DISTANT_CODE" -eq 2 ] \
  || { echo "FAIL: blocker 8 lines away suppressed a real claim (exit $DISTANT_CODE, want 2)"; exit 1; }
echo "ok: distant blocker does not suppress"

echo "PASS: prompt-only-enforcement-guard stderr contract"
