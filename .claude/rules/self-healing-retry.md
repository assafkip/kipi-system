# Self-Healing Retry Contract

The retry discipline for ANY phased or step-based job (pipelines, launchd jobs,
heartbeat sweeps, harvest runs) — extracted 2026-07-01 from morning-pipeline.md,
where it was encoded while every other job reinvented or omitted it.

Naming note: AUTONOMOUS-SYSTEMS.md uses "self-healing" for launchd durability
(jobs surviving updates and being noticed when they die). This rule owns the
other sense: what a RUNNING job does when one of its steps fails.

## The contract

On step failure:

1. **Capture the error output** from the failed step. No diagnosis from memory.
2. **Ground before you fix:** read the job's actual artifacts (bus files,
   run-logs, state files) to confirm what is missing or malformed. Confirm the
   error is real before acting on it.
3. **Apply a targeted fix** (config, path, missing dependency), then re-run
   ONLY the failed step. Never restart the whole job to retry one step.
4. **3 attempts max per step.** On the 3rd failure: STOP and surface the
   diagnosis — error trace, fixes attempted, current artifact state. No
   monolithic fallback.
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
