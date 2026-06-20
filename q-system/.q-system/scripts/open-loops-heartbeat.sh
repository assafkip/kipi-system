#!/bin/bash
# FLEET open-loops heartbeat (launchd-fired). One job sweeps every registered instance
# (+ the skeleton). For each instance that has open [needs you] loops, it wakes a
# HEADLESS agent (claude -p) IN that instance to advance/close them. Safe by construction:
#   - Only wakes an agent for instances that actually have open work (cheap no-op otherwise).
#   - The agent prompt forbids pushing to an external repo without clear maintainer approval;
#     destructive ops stay blocked by each instance's PreToolUse hooks.
#   - 30-min timeout per instance so a runaway agent can't spin forever.
#   - Slacks the founder on agent failure (via slack-notify.sh); logs every run centrally.
# Disable: launchctl unload ~/Library/LaunchAgents/com.kipi.openloops-heartbeat.plist
set -uo pipefail

SKEL="${KIPI_REPO:-/Users/assafkipnis/projects/kipi-system}"
REGISTRY="$SKEL/instance-registry.json"
LOG="$SKEL/q-system/output/open-loops-heartbeat.log"
TS() { date '+%Y-%m-%d %H:%M:%S'; }

command -v claude >/dev/null 2>&1 || { echo "$(TS) heartbeat: no claude CLI -> skip" >> "$LOG"; exit 0; }
if command -v timeout >/dev/null 2>&1; then TO="timeout 1800"
elif command -v gtimeout >/dev/null 2>&1; then TO="gtimeout 1800"
else TO=""; fi

# Per-instance prompt. $1=abs path to open-loops.py, $2=abs qroot (controlled paths,
# no shell-special chars), so the unquoted heredoc only substitutes those two.
build_prompt() {
  cat <<PROMPT_EOF
Autonomous open-loops heartbeat for THIS instance. Be terse; act only on what is actionable.
1. Run: python3 "$1" --report   then read the registry at $2/memory/open-loops.json
2. For EACH loop tagged [needs you], do the next concrete action toward closure, then update that loop in $2/memory/open-loops.json (set status "closed" with a note/URL when done):
   - OSS PR waiting on a maintainer: check via gh (gh issue view <n> --repo <r> --json comments,state ; gh pr list). Push the PR ONLY if a maintainer has clearly approved/invited it (follow the loop's next_action). No clear approval -> do nothing, leave it open.
   - Internal work in this instance: drive it through prd-os in full (PRD -> review -> tests -> blast radius -> closeout), making all triage/approve/merge decisions yourself per the autonomy contract.
3. Hard limits: no force-push, no git reset --hard, no branch deletion, no destructive ops, and NEVER publish to an external repo without clear maintainer approval. When unsure, do nothing.
4. Slack the founder ONLY on a meaningful change (pushed a PR, closed a loop, maintainer replied): bash $2/.q-system/scripts/slack-notify.sh "<one line>". Silent otherwise.
5. Report what you did in 3-5 lines. Do not invent new work beyond the open loops.
PROMPT_EOF
}

work_instance() {
  local name="$1" path="$2"
  [ -d "$path" ] || return 0
  local script qroot
  if [ -f "$path/q-system/q-system/.q-system/scripts/open-loops.py" ]; then
    script="$path/q-system/q-system/.q-system/scripts/open-loops.py"; qroot="$path/q-system/q-system"
  elif [ -f "$path/q-system/.q-system/scripts/open-loops.py" ]; then
    script="$path/q-system/.q-system/scripts/open-loops.py"; qroot="$path/q-system"
  else
    return 0   # instance has no open-loops.py yet (pre-propagation) -> skip
  fi
  local out count
  out="$(CLAUDE_PROJECT_DIR="$path" python3 "$script" --report 2>/dev/null || true)"
  count="$(printf '%s\n' "$out" | grep -c '\[needs you\]' || true)"
  if [ "${count:-0}" -eq 0 ]; then
    echo "$(TS) heartbeat[$name]: 0 open loops -> skip" >> "$LOG"
    return 0
  fi
  echo "$(TS) heartbeat[$name]: $count open loop(s) -> waking headless agent" >> "$LOG"
  local prompt; prompt="$(build_prompt "$script" "$qroot")"
  if ! ( cd "$path" && $TO claude -p "$prompt" >> "$LOG" 2>&1 ); then
    echo "$(TS) heartbeat[$name]: agent run failed/timeout" >> "$LOG"
    bash "$SKEL/q-system/.q-system/scripts/slack-notify.sh" "Kipi heartbeat[$name]: autonomous run failed/timeout -- check open-loops-heartbeat.log" 2>/dev/null || true
  fi
}

echo "$(TS) heartbeat: fleet sweep start" >> "$LOG"
work_instance "kipi-system" "$SKEL"
while IFS='|' read -r name path; do
  [ -z "$name" ] && continue
  [ "$path" = "$SKEL" ] && continue
  work_instance "$name" "$path"
done < <(python3 -c "
import json
try:
    d=json.load(open('$REGISTRY'))
    for i in d.get('instances',[]):
        if 'status' in i and str(i['status']).startswith('merged'): continue
        print(i['name'] + '|' + i['path'])
except Exception: pass
" 2>/dev/null)
echo "$(TS) heartbeat: fleet sweep complete" >> "$LOG"
exit 0
