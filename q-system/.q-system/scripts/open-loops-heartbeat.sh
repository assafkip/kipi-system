#!/bin/bash
# Autonomous open-loops heartbeat (launchd-fired). Replaces the ping approach:
# instead of notifying the founder, it wakes a HEADLESS agent (claude -p) to advance
# or close each open loop on its own. Safe by construction:
#   - Only fires the agent when there is open [needs you] work (cheap no-op otherwise).
#   - The agent prompt forbids pushing to an external repo without clear maintainer
#     approval, and all destructive ops stay blocked by the repo's PreToolUse hooks.
#   - Timeout-guarded so a runaway agent can't spin forever.
#   - Logs every run to q-system/output/open-loops-heartbeat.log.
# Disable: launchctl unload ~/Library/LaunchAgents/com.kipi.openloops-heartbeat.plist
set -uo pipefail

REPO="${KIPI_REPO:-/Users/assafkipnis/projects/kipi-system}"
SCRIPT="$REPO/q-system/.q-system/scripts/open-loops.py"
LOG="$REPO/q-system/output/open-loops-heartbeat.log"
TS() { date '+%Y-%m-%d %H:%M:%S'; }
[ -f "$SCRIPT" ] || exit 0

OUT="$(CLAUDE_PROJECT_DIR="$REPO" python3 "$SCRIPT" --report 2>/dev/null || true)"
COUNT="$(printf '%s\n' "$OUT" | grep -c '\[needs you\]' || true)"
if [ "${COUNT:-0}" -eq 0 ]; then
  echo "$(TS) heartbeat: no open [needs you] loops -> skip (no agent run)" >> "$LOG"
  exit 0
fi

if ! command -v claude >/dev/null 2>&1; then
  echo "$(TS) heartbeat: claude CLI not found -> skip" >> "$LOG"
  exit 0
fi

# portable 30-min timeout (macOS has no `timeout` by default)
if command -v timeout >/dev/null 2>&1; then TO="timeout 1800"
elif command -v gtimeout >/dev/null 2>&1; then TO="gtimeout 1800"
else TO=""; fi

read -r -d '' PROMPT <<'PROMPT_EOF' || true
Autonomous open-loops heartbeat run. You are a headless agent. Be terse and act only on what is actionable.

1. Run `python3 q-system/.q-system/scripts/open-loops.py --report` and read q-system/memory/open-loops.json.
2. For EACH open loop tagged [needs you], do the next concrete action toward closure, then update the loop in open-loops.json:
   - OSS PR waiting on a maintainer: check the issue/PR via `gh issue view <n> --repo <r> --json comments,state` (and `gh pr list`). ONLY if a maintainer has clearly approved or invited the PR (an explicit affirmative comment) do you push it: follow the exact steps in the loop's next_action / the q-system/output/*-pr-drafts file, then set the loop status to "closed" with the PR URL. If there is NO clear maintainer approval yet, do NOTHING for that loop and leave it open.
   - Internal kipi-system work: drive it through prd-os in full (new PRD -> review -> tests -> blast radius -> closeout), making all triage/approve/merge decisions yourself per the autonomy contract. Close the loop when done.
3. Hard limits (do NOT violate): no force-push, no `git reset --hard`, no branch deletion, no destructive ops, and NEVER publish to an external repo without a clear maintainer approval. When unsure, leave the loop open and do nothing.
4. Slack the founder ONLY on a meaningful change: if you pushed a PR, closed a loop, or a maintainer newly replied, run `bash q-system/.q-system/scripts/slack-notify.sh "<one concise line>"`. If nothing changed (loops still just waiting on a maintainer), stay SILENT -- do not Slack.
5. Report what you did in 3-5 lines. Do not invent new work beyond the open loops.
PROMPT_EOF

echo "$(TS) heartbeat: $COUNT open loop(s) -> waking headless agent" >> "$LOG"
cd "$REPO" || exit 0
if ! $TO claude -p "$PROMPT" >> "$LOG" 2>&1; then
  echo "$(TS) heartbeat: agent run ended (nonzero or timeout)" >> "$LOG"
  bash "$REPO/q-system/.q-system/scripts/slack-notify.sh" "Kipi heartbeat: the autonomous run failed or timed out -- check q-system/output/open-loops-heartbeat.log" 2>/dev/null || true
fi
echo "$(TS) heartbeat: run complete" >> "$LOG"
exit 0
