---
description: The 8 exit conditions every agentic/phased/scheduled loop must account for, each mapped to its real enforcer. Audit new loops against this.
paths:
  - "**/scripts/**"
  - "**/hooks/**"
  - "**/*heartbeat*"
  - "**/*loop*"
  - "**/launchd*"
  - "**/*.plist"
---

# Loop Exits (audit checklist)

A loop with one exit hangs. A durable loop declares its exits in CODE before the
prompt is written. This file is the MAP: eight exit conditions, each pointed at
the fleet's actual enforcer (script:line). The enforcement lives in the cited
code, not in this file. This file is what you audit a new loop against.

Same shape as `wiring-check.md`: a checklist that references real gates, not a
prose rule that claims to enforce anything.

## Fires when

- Building or editing a phased/step-based job (pipeline, launchd job, heartbeat,
  harvest sweep, any autonomous `claude -p` run).
- Building an agent loop or a `Workflow`/`ScheduleWakeup`-driven run.
- Auditing whether an existing loop can actually terminate.

## Does not fire

- One-shot commands, single tool calls, pure conversational turns. A loop that
  cannot iterate needs no exit audit.

## Before you build: 4 preconditions

A loop earns its cost only when all four are true. Miss one and the setup takes
more than it returns (a one-shot script or a manual pass is cheaper).

1. **Repeats at least weekly.** Less often and the setup never amortizes.
2. **Something can automatically fail the work** (a test, type check, linter,
   build). This is exit 1's enforcer already existing. No auto-fail, no loop.
3. **The token budget can absorb the waste.** Loops re-read context, retry, and
   explore. `token-guard.py` caps the bleed but the run still costs more than a
   single pass.
4. **The agent has senior-engineer tools:** logs, a reproduction environment,
   the ability to run what it writes and see what breaks.

Good first loops are boring: CI triage, dependency bumps, lint-and-fix, flaky-
test repro, issue-to-PR on a codebase with strong tests. Bad first loops are the
interesting ones (architecture rewrites, auth, payments) where "done" is a
judgment call.

## The 8 exits and this fleet's enforcer

| # | Exit | What triggers it | Enforcer (verified 2026-07-21) |
|---|------|-----------------|-------------------------------|
| 1 | goal met | an evaluator scores output against a rubric, stops on pass | `prd_runner.py gates run` exit 0/nonzero (`plugins/prd-os/scripts/prd_runner.py` `cmd_gates`); verification-loops bounded contract (default 3, stop on first green) |
| 2 | turn cap | hard ceiling on iterations, harness-counted not prompt-counted | `token-guard.py` `VOLUME_CEILING=50` PreToolUse block (`q-system/.q-system/token-guard.py`); fires in autonomous runs too (`CLAUDECODE=1` gate) |
| 3 | budget cap | tokens/dollars/spend limit | Interactive: call-count + `AGENT_CEILING=30` + `MCP_RATE_LIMIT=30/60s` proxies (token-guard.py, those constants). `Workflow` harness: real `budget.total`/`budget.spent()`. No dollar meter is exposed to the hook layer, so proxies are the ceiling |
| 4 | wall clock | elapsed-time deadline, independent of progress | Autonomous: `timeout 1800` around `claude -p` (`open-loops-heartbeat.sh`, the `TO=` wrapper) + `launchd-health-check.py` silent-death watchdog. Interactive: the founder is the wall clock |
| 5 | no progress | state unchanged N turns in a row | token-guard 6 coded detectors: exact-retry hash `RETRY_LIMIT=3`, edit-spiral, read-spiral, grep-drift, time-stall (`STALL_TIME_SECONDS=120`), commit-gated volume. Volume ceiling resets on a real commit, so it gates lack-of-progress not raw volume |
| 6 | human interrupt | approval gate + kill switch outside the loop | `~/.claude/hooks/destructive-op-deny.sh` (agent cannot self-grant `ALLOW_DESTRUCTIVE=1`); prd-os approval gates; capability-token grants |
| 7 | error threshold | consecutive failures, resets on success | `self-healing-retry.md` 3-attempts-max; environmental-trigger class stops on attempt 1 (auth error, server crash, hard-down); `rca-notify` hook opens a postmortem on failure |
| 8 | external event | webhook/poll on the actual task | `open-loops-heartbeat.sh` pings only on a meaningful change (maintainer replied, PR merged, loop closed); `status:"merged"`/`"closed"` tracking in `open-loops.json` |

## Auditing a NEW loop

Not every loop needs all 8. Match the exit to the loop's risk:

- **Any autonomous/scheduled loop** owns 2 (turn cap), 4 (wall clock), 7 (error
  threshold) at minimum. A 3am run with none of these is the runaway-bill loop.
- **Any loop that produces a checkable artifact** owns 1 (goal met). "The model
  said it is done" is not exit 1; a gate that can fail is.
- **Any loop that can take a risky action** owns 6 (human interrupt). The kill
  switch lives OUTSIDE the loop (a hook the agent cannot self-clear), never a
  self-check inside it.
- **Any loop waiting on external state** owns 8. Poll the thing that actually
  changed, not a liveness proxy.
- 3 (budget) and 5 (no progress) come free fleet-wide via `token-guard.py` for
  any `claude`/`claude -p` actor. A loop OUTSIDE that runtime (a bare Python
  runner) inherits neither and must code its own cap.

If a new loop skips an exit its risk class calls for, that skip is a finding:
capture it (`no-orphan-findings.md`), do not just note it.

## Loop-health metric: cost per accepted change

The metric that says whether a loop is winning is not tokens spent or PRs opened.
It is **cost per accepted change**, and the rate that matters is the fraction of
loop output the founder actually accepts. Below ~50% accepted and the founder is
doing the review the loop was meant to remove; the loop is losing.

**The self-merging blind spot (fleet-specific):** `open-loops-heartbeat.sh`
merges its own PRs under the autonomy contract, so there is NO accepted-change
signal by construction, the founder is not in the accept step. The `sycophancy.md`
`pi` metric is adjacent (are recommendations rubber-stamped) but measures
decisions, not shipped loop output. Until an accepted-change rate is instrumented,
the comprehension hedge for self-merging loops is a glanceable visual of what
shipped (the fleet-loop board), not an in-loop gate. Do not pretend the loop is
winning because it is busy.

## Where the fleet is thin (honest, do not paper over)

- **Exit 3, true token/dollar meter:** none exists at the interactive hook layer
  because Claude Code does not expose per-run token spend to a PreToolUse hook.
  The call-count ceiling is a proxy, and the "never hold large API responses"
  line in `token-discipline.md` is Layer-2 prose with no coded per-response cap.
  Accepted posture (two-layer by design), not a defect to patch reflexively.
- **Exit 4, interactive loop:** no absolute in-session deadline block. Covered
  by the founder being present. If an interactive loop ever runs unattended,
  this becomes a real gap.

## Provenance

2026-07-21: a LinkedIn post ("your agent loop needs 8 exits, most ship one")
prompted a fleet audit. Grounding against real enforcers showed 6 of 8 solidly
coded, exits 3 and 4 covered by proxies at the right layer, and the post's
single "state-hash" for exit 5 is thinner than the fleet's 6 detectors. No new
build was warranted. This checklist is the durable artifact so the next new loop
gets audited instead of re-derived.

## Cross-references

`self-healing-retry.md` (exits 5, 7 for phased jobs) · `token-discipline.md`
(exits 2, 3, 5 enforcer) · `wiring-check.md` (the sibling audit pattern) ·
`founder-notifications.md` (how exit 8 pings reach the founder) ·
`morning-pipeline.md` (the reference multi-phase loop binding these).
