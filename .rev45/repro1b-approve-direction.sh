#!/usr/bin/env bash
# REPRO 1b: the SAME extracted block, same real `pr_head_sha`, but the stale session
# it reads happens to have APPROVED. Shows the dangerous direction of repro 1:
# kipi/codex-approved=SUCCESS lands on a commit that session never read.
# Only the agent-verdict output is stubbed here (a Codex session that approved an
# earlier sha); the head sha is the real live head of PR #34.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
. "$ROOT/q-system/.q-system/scripts/pr-verdict-lib.sh"
ISSUE="ASK-221"; PR_NUM="34"
STATE_DIR="$(dirname "$0")/state2"; mkdir -p "$STATE_DIR"
LOG="$(dirname "$0")/repro1b.log"
say() { printf '  say| %s\n' "$*"; }
POSTED="$(dirname "$0")/posted1b.txt"; : > "$POSTED"
gh() { if [ "${1:-}" = "api" ]; then printf 'WOULD POST: gh %s\n' "$*" >>"$POSTED"; return 0; fi; command gh "$@"; }

SYNC="$(dirname "$0")/sync-stub-approve.sh"
cat > "$SYNC" <<'STUB'
#!/usr/bin/env bash
case "${1:-}" in
  delegate) echo "ASK-221: delegated to Codex (u-codex)"; exit 0 ;;
  agent-verdict)
    # a COMPLETE Codex session that reviewed an older commit and approved it
    echo "session=c92cd12d status=complete agent=Codex created=2026-07-30T00:27:59Z"
    echo "verdict=APPROVE"; echo "findings=0"; exit 0 ;;
esac
exit 1
STUB
chmod +x "$SYNC"
python3() { if [ "${1:-}" = "$SYNC" ]; then shift; "$SYNC" "$@"; else command python3 "$@"; fi; }

# ---- verbatim linear-worker.sh:1122-1158 ----
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
      say "$ISSUE: codex verdict UNSTATED on PR #$PR_NUM. Nothing posted."
    fi
# ---- end verbatim ----
echo
sed 's/^/  /' "$POSTED"
