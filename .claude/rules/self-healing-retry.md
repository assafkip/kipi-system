---
description: What a RUNNING job does when a step fails - capture, ground, targeted re-run, 3 attempts then escalate to a peer model, environmental failures stop at 1, log every attempt.
paths:
  - "**/*.py"
  - "**/*.sh"
  - "**/*.plist"
  - "**/*.yml"
---

# Self-Healing Retry Contract

The retry discipline for ANY phased or step-based job (pipelines, launchd jobs,
heartbeat sweeps, harvest runs) — extracted 2026-07-01 from morning-pipeline.md,
where it was encoded while every other job reinvented or omitted it.

Naming note: AUTONOMOUS-SYSTEMS.md's "self-healing" is launchd durability; this
rule owns the other sense, what a RUNNING job does when a step fails.

## The contract

Steps 1-3 and 5 are judgment, not enforced; the coded blockers are
`token-guard.py` and `run-step-audit.py` (see "Enforcement boundary").

On step failure:

1. **Capture the error output** from the failed step. No diagnosis from memory.
2. **Ground before you fix:** read the job's actual artifacts (bus files,
   run-logs, state files) to confirm what is missing or malformed. Confirm the
   error is real before acting on it.
3. **Apply a targeted fix** (config, path, missing dependency), then re-run
   ONLY the failed step. Never restart the whole job to retry one step.
4. **3 attempts max, then escalate to a PEER, not the founder.** Hand the
   diagnosis to another model — `Agent(subagent_type='general-purpose',
   model='fable')`. Three failures mean THIS model is stuck, not that a human is
   needed; the founder comes after Fable is too. Enforced by `FABLE_ESCALATION`
   in `token-guard.py`, which carries the scar.
5. **Environmental failures stop on attempt 1.** An authentication error, a
   server crash, or a hard-down external service is `environmental-trigger`
   class (the rca skill's cause taxonomy — shared vocabulary, one failure-class
   model forward and backward), not `latent-defect`. Retrying logic cannot fix
   an environment; surface it immediately.
6. **Log every attempt** to the job's run-log (`phase`/`step`, `attempt`,
   `error`, `fix_applied`) so the post-run step audit
   (`run-step-audit.py`) sees retries, not silence.

## Enforcement boundary

Rules 1-3 and 5 are judgment; this file teaches them. The deterministic slices
live in code, not prose: the attempt cap belongs in each job's runner script
(morning: the orchestrator's retry loop), `token-guard.py` is the hook that
blocks identical-input retries in interactive sessions, and unlogged steps are
caught by the `run-step-audit.py` validator script. A job that claims this
contract but has no coded cap is prompt-only and does not comply.

## Bindings

- Morning pipeline: `.claude/rules/morning-pipeline.md` "Self-Healing Loop" is
  this contract plus morning-specific diagnosis steps (verify-bus, agent files,
  bus artifact names) and the MCP hard-down server list.
- RCA: when a step exhausts its attempts, the surfaced diagnosis is the input
  to an rca-skill postmortem; tag the cause with the same
  environmental-trigger / latent-defect vocabulary used in step 5.
