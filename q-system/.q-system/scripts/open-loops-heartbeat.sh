#!/bin/bash
# FLEET open-loops heartbeat (launchd-fired). One job sweeps every registered instance
# (+ the skeleton). For each instance that has open [needs you] loops, it wakes a
# HEADLESS agent (claude -p) IN that instance to advance/close them. Safe by construction:
#   - Only wakes an agent for instances that actually have open work (cheap no-op otherwise).
#   - The agent prompt forbids pushing to an external repo without clear maintainer approval;
#     destructive ops stay blocked by each instance's PreToolUse hooks.
#   - 30-min timeout per instance so a runaway agent can't spin forever.
#   - Slacks the founder on agent failure (via slack-notify.sh); logs every run centrally.
#   - Writes a structured run-log and self-audits post-sweep (run-step-audit.py).
# Disable: launchctl unload ~/Library/LaunchAgents/com.kipi.openloops-heartbeat.plist
set -uo pipefail

# Default the repo root to this script's location (q-system/.q-system/scripts ->
# three levels up), so the skeleton carries no hardcoded home path. Override
# with KIPI_REPO if the script is relocated.
SKEL="${KIPI_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)}"
REGISTRY="$SKEL/instance-registry.json"
LOG="$SKEL/q-system/output/open-loops-heartbeat.log"
RUNLOG="$SKEL/q-system/output/heartbeat-run-last.json"
RUNLOG_TMP="$RUNLOG.steps.tmp"
TS() { date '+%Y-%m-%d %H:%M:%S'; }

# Single-writer chokepoint for the structured run-log (2026-07-01: the freeform
# .log was unauditable -- a sweep could miss instances and nothing diffed
# expected-vs-actual; run-step-audit.py now does, post-sweep).
log_step() {  # log_step <instance-name> <completed|skipped|failed> [note]
  python3 -c '
import json, sys
print(json.dumps({"id": sys.argv[1], "status": sys.argv[2], "note": sys.argv[3] if len(sys.argv) > 3 else ""}))
' "$1" "$2" "${3:-}" >> "$RUNLOG_TMP"
}

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
4. Slack the founder ONLY on a meaningful change (pushed a PR, closed a loop, maintainer replied): bash $2/.q-system/scripts/slack-notify.sh "<one line>". The project name is prefixed automatically -- do NOT add it yourself. Silent otherwise.
5. Report what you did in 3-5 lines. Do not invent new work beyond the open loops.
PROMPT_EOF
}

work_instance() {
  local name="$1" path="$2"
  if [ ! -d "$path" ]; then log_step "$name" skipped "path missing"; return 0; fi
  local script qroot
  if [ -f "$path/q-system/q-system/.q-system/scripts/open-loops.py" ]; then
    script="$path/q-system/q-system/.q-system/scripts/open-loops.py"; qroot="$path/q-system/q-system"
  elif [ -f "$path/q-system/.q-system/scripts/open-loops.py" ]; then
    script="$path/q-system/.q-system/scripts/open-loops.py"; qroot="$path/q-system"
  else
    log_step "$name" skipped "no open-loops.py (pre-propagation)"
    return 0
  fi
  local out count
  out="$(CLAUDE_PROJECT_DIR="$path" python3 "$script" --report 2>/dev/null || true)"
  count="$(printf '%s\n' "$out" | grep -c '\[needs you\]' || true)"
  if [ "${count:-0}" -eq 0 ]; then
    echo "$(TS) heartbeat[$name]: 0 open loops -> skip" >> "$LOG"
    log_step "$name" completed "0 open loops"
    return 0
  fi
  echo "$(TS) heartbeat[$name]: $count open loop(s) -> waking headless agent" >> "$LOG"
  local prompt; prompt="$(build_prompt "$script" "$qroot")"
  if ( cd "$path" && KIPI_INSTANCE_NAME="$name" $TO claude -p "$prompt" >> "$LOG" 2>&1 ); then
    log_step "$name" completed "agent ran ($count loops)"
  else
    echo "$(TS) heartbeat[$name]: agent run failed/timeout" >> "$LOG"
    log_step "$name" failed "agent run failed/timeout"
    KIPI_INSTANCE_NAME="$name" bash "$SKEL/q-system/.q-system/scripts/slack-notify.sh" "heartbeat: autonomous run failed/timeout -- check open-loops-heartbeat.log" 2>/dev/null || true
  fi
}

echo "$(TS) heartbeat: fleet sweep start" >> "$LOG"
: > "$RUNLOG_TMP"
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

# Post-sweep self-audit: expected (registry + skeleton) vs logged. Catches the
# case launchd-health cannot: the sweep exits 0 but never reached an instance.
python3 -c "
import json
steps = [json.loads(l) for l in open('$RUNLOG_TMP') if l.strip()]
json.dump({'job': 'open-loops-heartbeat', 'ts': '$(TS)', 'steps': steps}, open('$RUNLOG', 'w'), indent=1)
expected = ['kipi-system']
try:
    d = json.load(open('$REGISTRY'))
    for i in d.get('instances', []):
        if 'status' in i and str(i['status']).startswith('merged'): continue
        expected.append(i['name'])
except Exception: pass
json.dump(expected, open('$RUNLOG_TMP.expected', 'w'))
" 2>> "$LOG"
if ! AUDIT_OUT="$(python3 "$SKEL/q-system/.q-system/scripts/run-step-audit.py" \
    --manifest "$RUNLOG_TMP.expected" --log "$RUNLOG" --job open-loops-heartbeat 2>&1)"; then
  echo "$(TS) heartbeat AUDIT: $AUDIT_OUT" >> "$LOG"
  bash "$SKEL/q-system/.q-system/scripts/slack-notify.sh" "heartbeat step-audit: $(printf '%s' "$AUDIT_OUT" | head -3 | tr '\n' ' ')" 2>/dev/null || true
else
  echo "$(TS) heartbeat AUDIT: $AUDIT_OUT" >> "$LOG"
fi
rm -f "$RUNLOG_TMP" "$RUNLOG_TMP.expected" 2>/dev/null || true
exit 0
