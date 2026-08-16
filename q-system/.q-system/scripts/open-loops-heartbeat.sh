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

# Failures observed during this sweep. The script used to end in an
# unconditional `exit 0`, so launchd recorded a clean run even when an
# instance's agent died -- which made fleet-health-daily.py's `launchd-failing`
# detector structurally blind to this job and left its failures in Slack and a
# freeform log, never in Linear (ASK-184). The exit code IS the wire to Linear:
# non-zero here -> LastExitStatus non-zero -> a deduped Linear issue on the next
# fleet-health run. Counted, not `set -e`, so one bad instance still lets the
# rest of the fleet sweep finish.
SWEEP_FAILURES=0

# Single-writer chokepoint for the structured run-log (2026-07-01: the freeform
# .log was unauditable -- a sweep could miss instances and nothing diffed
# expected-vs-actual; run-step-audit.py now does, post-sweep).
# --- environmental classification (ASK-869) ---------------------------------
# Set once the machine-wide condition is seen; every later instance is then
# skipped without waking an agent. Empty means the sweep is healthy.
ENV_HALT=""

# DERIVED FROM WHAT THE LOG ACTUALLY CARRIED, not from what an exhausted CLI
# might plausibly print. The observed line, once per failing instance, was:
#   You've hit your weekly limit - resets Aug 18 at 2pm (America/Los_Angeles)
# The auth siblings are included because they are the same CLASS -- the runner
# cannot run at all, and no instance can fix that for another -- but the match
# stays narrow on purpose. A loose pattern here silently converts ordinary
# per-instance failures into a fleet-wide halt, which is worse than the noise
# this replaces: the sweep would stop on one instance's ordinary bad day.
# ANCHORED AT THE START OF A LINE, NOT MATCHED ANYWHERE (PR #198 review, minor).
# The runner emits this as a line of its own; an AGENT that merely writes about
# limits emits it inside a sentence or a bullet. Matched as a bare substring, an
# agent discussing this very issue and then exiting non-zero would halt the whole
# fleet and report the runner as dead -- a false halt is worse than the noise this
# replaces, because it stops work that could have run.
#
# This is the same shape as ASK-747, fixed the same way: content that MENTIONS a
# marker is not the marker being raised. There the fix was a column-0 trailer;
# here it is a line anchor. Leading whitespace is tolerated (up to 3) because the
# CLI pads some of these, but an indented quote inside agent prose does not reach
# that far left.
ENV_MARKERS="(you've |you have )?hit your (weekly|usage|session|[0-9]+-hour) limit|usage limit reached|credit balance is too low|invalid api key|authentication_error|please run /login"

is_environmental() {  # is_environmental <agent-output>
  printf '%s' "${1:-}" | grep -qiE "^[[:space:]]{0,3}($ENV_MARKERS)"
}

environmental_reason() {  # environmental_reason <agent-output> -> one line
  printf '%s' "${1:-}" \
    | grep -iE "^[[:space:]]{0,3}($ENV_MARKERS)" \
    | head -1 | tr -d '\n' | cut -c1-120
}

log_step() {  # log_step <instance-name> <completed|skipped|failed> [note]
  python3 -c '
import json, sys
print(json.dumps({"id": sys.argv[1], "status": sys.argv[2], "note": sys.argv[3] if len(sys.argv) > 3 else ""}))
' "$1" "$2" "${3:-}" >> "$RUNLOG_TMP"
}

command -v claude >/dev/null 2>&1 || { echo "$(TS) heartbeat: no claude CLI -> skip" >> "$LOG"; exit 0; }
# Founder decision 2026-08-01: pin the per-instance agents' model; unpinned they
# ride the interactive default (Fable on 2026-08-01) and burn quota unattended.
export ANTHROPIC_MODEL="claude-opus-5"
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
  # ONCE THE MACHINE HAS REFUSED, EVERY LATER INSTANCE IS UNATTEMPTED (ASK-869).
  # Not failed -- nobody tried it. This is the line that turns N tickets into one
  # and stops the sweep burning ~6s per instance on runs that cannot succeed.
  if [ -n "$ENV_HALT" ]; then
    log_step "$name" skipped "not attempted: $ENV_HALT"
    return 0
  fi
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
  # Byte offset BEFORE the run so the classifier below reads exactly this
  # instance's output. Reading a fixed tail of $LOG instead would let a previous
  # SWEEP's limit line -- the log persists across runs -- halt a healthy sweep,
  # which is this bug pointed the other way.
  local log_before; log_before="$(wc -c < "$LOG" 2>/dev/null || echo 0)"
  # </dev/null: claude -p reads stdin; without this it drains the while-read loop's
  # process-substitution feed (lines below) and truncates the sweep after the first
  # agent-waking instance. See rca-heartbeat-tail-skip-2026-07-05.md.
  if ( cd "$path" && KIPI_INSTANCE_NAME="$name" $TO claude -p "$prompt" </dev/null >> "$LOG" 2>&1 ); then
    log_step "$name" completed "agent ran ($count loops)"
  else
    # WHOSE FAILURE IS IT (ASK-869). An exhausted account is not a property of
    # this instance; it is a property of the MACHINE, and it is identical for
    # every instance the sweep has not reached yet. Measured 2026-08-15: the
    # weekly limit killed ten runs in one sweep and this branch filed ten
    # tickets, plus a step-audit ticket for the ten "failed" steps, plus the
    # job's own exit-1 ticket. Twelve tickets for one fact, and the sweep kept
    # waking agents for ~6s each after the answer was already known.
    #
    # `.claude/rules/self-healing-retry.md` step 5 already states the rule --
    # environmental failures stop on attempt 1 and surface immediately, because
    # retrying cannot fix an environment. The heartbeat simply never applied it.
    local agent_out; agent_out="$(tail -c +$((log_before + 1)) "$LOG" 2>/dev/null)"
    if is_environmental "$agent_out"; then
      ENV_HALT="$(environmental_reason "$agent_out")"
      echo "$(TS) heartbeat[$name]: environmental failure ($ENV_HALT) -- halting the sweep" >> "$LOG"
      # skipped, NOT failed: the environment refused the run, the instance did
      # not fail at anything. Recording it as a failure is what put a step-audit
      # ticket on top of the pile.
      log_step "$name" skipped "environmental: $ENV_HALT"
      SWEEP_FAILURES=$((SWEEP_FAILURES + 1))
      return 0
    fi
    echo "$(TS) heartbeat[$name]: agent run failed/timeout" >> "$LOG"
    log_step "$name" failed "agent run failed/timeout"
    SWEEP_FAILURES=$((SWEEP_FAILURES + 1))
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

# THE ONE ALERT (ASK-869). Fired here rather than at the point of detection so it
# can state how many instances went unattempted -- the number is only known once
# the loop has finished skipping them. One condition, one ticket, and it names
# what a human would otherwise have to reconstruct from ten identical ones.
if [ -n "$ENV_HALT" ]; then
  # COUNT ONLY WHAT THE HALT SKIPPED (PR #198 review, minor). Counting every
  # `skipped` row swept in registry drift (missing path, pre-propagation) and the
  # instance that actually failed, so the one alert overstated itself -- reported
  # 5 where the truth was 2. A number a human cannot reconcile against the run-log
  # is worse than no number: it is the ticket arguing with its own evidence.
  ENV_SKIPPED="$(grep -c 'not attempted' "$RUNLOG_TMP" 2>/dev/null || echo 0)"
  bash "$SKEL/q-system/.q-system/scripts/slack-notify.sh" \
    "heartbeat: sweep HALTED, the runner itself is unavailable ($ENV_HALT). $ENV_SKIPPED instance(s) not attempted -- this is one machine-wide condition, not one fault per instance. Nothing to fix per repo; the sweep resumes on its own when the runner is available." \
    2>/dev/null || true
fi

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
  SWEEP_FAILURES=$((SWEEP_FAILURES + 1))
else
  echo "$(TS) heartbeat AUDIT: $AUDIT_OUT" >> "$LOG"
fi
rm -f "$RUNLOG_TMP" "$RUNLOG_TMP.expected" 2>/dev/null || true

# A `skipped` step (missing instance path, pre-propagation instance) is registry
# drift, not a job failure, and is deliberately NOT counted here -- paging weekly
# on known drift is the alert-fatigue that teaches the founder to ignore the
# channel. A dead agent run, a step-audit mismatch, or an environmental halt
# reaches Linear.
#
# THE ENVIRONMENTAL HALT IS THE ONE EXCEPTION TO THE SENTENCE ABOVE (ASK-869, and
# PR #198 review caught this comment still claiming otherwise). That branch logs
# its instances `skipped` AND increments SWEEP_FAILURES, which reads as a
# contradiction until you separate the two questions the row and the counter
# answer. The row says what happened to that INSTANCE: nothing, nobody attempted
# it. The counter says whether the SWEEP did its job: it did not, it stopped
# early. Both are true at once, and ASK-184 requires the second to reach launchd
# or fleet-health's launchd-failing detector goes blind to this job.
if [ "$SWEEP_FAILURES" -gt 0 ]; then
  echo "$(TS) heartbeat: $SWEEP_FAILURES failure(s) this sweep -> exit 1" >> "$LOG"
  exit 1
fi
exit 0
