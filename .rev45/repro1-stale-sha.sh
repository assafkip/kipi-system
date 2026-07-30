#!/usr/bin/env bash
# REPRO 1: the worker posts kipi/codex-approved on the LIVE PR head sha while the
# verdict it posts comes from a Codex session that reviewed a DIFFERENT commit.
#
# The block under test is extracted VERBATIM from linear-worker.sh:1122-1158.
# Live inputs, not fixtures:
#   - pr_head_sha  -> the real pr-verdict-lib.sh function, real `gh pr view`
#   - agent-verdict -> the real linear-sync.py against live Linear (read-only query)
# Two things are stubbed, and only these:
#   - `gh api -X POST .../statuses/...`  -> printed, never sent (must not mutate GitHub)
#   - `$SYNC delegate`                   -> returns 0 without creating a session.
#     That models the documented 7-second ack: issueUpdate returns immediately,
#     Linear opens the AgentSession asynchronously. The read-back one line later
#     therefore still sees the PREVIOUS session. Actually delegating would start a
#     paid Codex session and mutate a Linear object, so it cannot be run for real.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT_DIR="$ROOT/q-system/.q-system/scripts"
. "$SCRIPT_DIR/pr-verdict-lib.sh"

ISSUE="ASK-221"
PR_NUM="34"
STATE_DIR="$(dirname "$0")/state"; mkdir -p "$STATE_DIR"
LOG="$(dirname "$0")/repro1.log"
say() { printf '  say| %s\n' "$*"; }

# stub 1: never POST to GitHub for real. Recorded to a file because the call site
# redirects stdout+stderr to /dev/null.
POSTED="$(dirname "$0")/posted.txt"; : > "$POSTED"
gh() {
  if [ "${1:-}" = "api" ]; then
    printf 'WOULD POST: gh %s\n' "$*" >> "$POSTED"
    return 0
  fi
  command gh "$@"
}

# stub 2: delegate returns success without a session existing yet (the ack race)
SYNC="$(dirname "$0")/sync-stub.sh"
cat > "$SYNC" <<'STUB'
#!/usr/bin/env bash
if [ "${1:-}" = "delegate" ]; then
  echo "ASK-221: delegated to Codex (u-codex)"; exit 0
fi
exec python3 "$(dirname "$0")/../q-system/.q-system/scripts/linear-sync.py" "$@"
STUB
chmod +x "$SYNC"
python3() { if [ "${1:-}" = "$SYNC" ]; then shift; "$SYNC" "$@"; else command python3 "$@"; fi; }

echo "== what the live Codex session on $ISSUE actually reviewed =="
command python3 "$SCRIPT_DIR/linear-sync.py" agent-verdict "$ISSUE" --agent Codex --body 2>/dev/null \
  | grep -m1 'PR_HEAD=' | sed 's/^/  session reviewed: /'
echo "  live PR #$PR_NUM head:   $(pr_head_sha "$PR_NUM")"
echo
echo "== the extracted worker block, run verbatim =="

# ---- BEGIN verbatim linear-worker.sh:1122-1158 ----
    CODEX_SHA="$(pr_head_sha "$PR_NUM")"
    CODEX_MARK="$STATE_DIR/codex-delegated-$PR_NUM-${CODEX_SHA:-nosha}"
    if [ -z "$CODEX_SHA" ]; then
      say "$ISSUE: no head sha for PR #$PR_NUM, so codex was NOT delegated (a review pinned to a guessed sha is worse than none)"
    elif [ -f "$CODEX_MARK" ]; then
      say "$ISSUE: codex already reviewed PR #$PR_NUM at ${CODEX_SHA:0:7}; not re-delegating (a paid session on unchanged code buys nothing)"
    elif python3 "$SYNC" delegate "$ISSUE" --agent Codex >>"$LOG" 2>&1; then
      : > "$CODEX_MARK"
      say "$ISSUE: delegated PR #$PR_NUM (${CODEX_SHA:0:7}) to codex for review"
    else
      say "WARN: $ISSUE: could not delegate to codex (the Claude review above stands, nothing is blocked)"
    fi

    CODEX_VERDICT="$(python3 "$SYNC" agent-verdict "$ISSUE" --agent Codex 2>/dev/null \
                     | sed -n 's/^verdict=//p' | head -1)"
    if [ -n "$CODEX_VERDICT" ]; then
      say "$ISSUE: codex verdict on PR #$PR_NUM: $CODEX_VERDICT"
      CODEX_STATE="failure"
      case "$CODEX_VERDICT" in "APPROVE"|"APPROVE WITH NITS") CODEX_STATE="success" ;; esac
      if gh api -X POST "repos/{owner}/{repo}/statuses/$CODEX_SHA" \
           -f "state=$CODEX_STATE" -f "context=kipi/codex-approved" \
           -f "description=$(printf '%.140s' "codex (gpt-5.6-sol, Linear agent): $CODEX_VERDICT")" \
           >/dev/null 2>&1; then
        say "$ISSUE: kipi/codex-approved=$CODEX_STATE posted on ${CODEX_SHA:0:7}"
      else
        say "WARN: $ISSUE: codex verdict read but the commit status did not post; no gate moved"
      fi
    else
      say "$ISSUE: codex verdict UNSTATED on PR #$PR_NUM (no complete session yet, or it errored). Nothing posted -- absent is not approved."
    fi
# ---- END verbatim ----

echo
echo "== the status that would reach GitHub =="
sed 's/^/  /' "$POSTED"
