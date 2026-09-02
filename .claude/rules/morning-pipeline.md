---
description: Morning routine pipeline execution rules
paths:
  - "q-system/.q-system/**"
  - "q-system/output/**"
---

# Preflight, Fail-Fast, and Audit Harness (ENFORCED)

**RETIRED 2026-08-30 (decisions.md RULE-2026-08-30-A). Nothing below is a live
instruction.** The 9-phase `/q-morning` agent pipeline this file describes does
not run. `/q-morning` is now `q-system/.q-system/scripts/morning-brief.py`, a
scheduled job (`com.kipi.morning-brief`, 07:00 local) that posts one Slack
message with four sections: today's calendar, mail needing an answer, owed
today, overnight jobs. A section it could not read says COULD NOT READ, never
"nothing". Its freshness is watched by a separate launchd job,
`com.kipi.morning-brief-deadman`. Do not run the preflight, the phase retry loop
or the phase plan below by hand.

The text is kept rather than deleted on purpose: decisions.md RULE-2026-08-30-A
holds the 37 agent prompt files under `q-system/.q-system/agent-pipeline/agents/`
on disk until the brief has run green for a week (earliest removal 2026-09-06),
and removing them is a separate deliberate act, not a cleanup. Read the rest of
this file as a record of what was retired.

Historical, for the retired pipeline only: every `/q-morning` run began by
reading `.q-system/preflight.md` for the tool manifest, known issues, session
budget and step completion log format. That preflight is what killed the
pipeline: it probed two MCP tool names that had been renamed, with fallback
"None. Halt."

**Every step must write its completion status to `output/morning-log-YYYY-MM-DD.json`.** If a step isn't logged, it didn't happen.

**After the routine ends, run the audit harness:**
```bash
python3 q-system/.q-system/audit-morning.py q-system/output/morning-log-YYYY-MM-DD.json
```

**After Phase 6 sycophancy audit, run the sycophancy harness:**
```bash
python3 q-system/.q-system/sycophancy-harness.py YYYY-MM-DD
```
If exit code = 1 (alert), the synthesizer MUST surface it prominently. Show audit output to the founder always.

Rules moved here from sycophancy.md (they are morning-coupled; the portable core is `sycophancy-core.md`):
1. When the sycophancy audit agent runs (Phase 6), its output is verified by `sycophancy-harness.py`. If the harness disagrees, the harness wins.
2. If `sycophancy-audit.json` shows `overall: "alert"`, the synthesizer MUST surface it as a dedicated section, not an FYI line.

## Self-Healing Loop (ENFORCED)

The generic contract (targeted fix, re-run failed step only, 3-attempt cap,
environmental failures stop on attempt 1) lives in
`.claude/rules/self-healing-retry.md` — any phased job follows it. Below is its
morning-pipeline binding.

On phase failure during `/q-morning`:
1. Capture stderr from the failed phase run
2. Run the bus verification harness to diagnose missing or malformed bus artifacts (instance-specific path, e.g. `python3 .q-system/verify-bus.py {date} {phase}`)
3. Read the failing agent file in `agent-pipeline/agents/` to confirm its declared output artifact names
4. Read the relevant bus artifact(s) at `agent-pipeline/bus/{date}/<artifact>.json`. Bus files are content-named, not phase-numbered: `hitlist.json`, `leads.json`, `preflight.json`, `calendar.json`, `linkedin-posts.json`, etc. There is no `{phase}.json`.
5. Apply a targeted fix (config, path, missing dependency)
6. Re-run ONLY the failed phase
7. Iterate up to 3 attempts max

On 3rd failure: STOP and surface diagnosis to the founder. Include error trace, attempted fixes, and current bus state.

Every retry attempt logs to `output/morning-log-YYYY-MM-DD.json` with `phase`, `attempt`, `error`, `fix_applied`.

**MCP hard-down exception (no retries):** If the failure is an authentication error, server crash, or hard-down for a configured MCP server (e.g., Notion, Apify, Gmail, Google Calendar, Linear, PostHog), STOP on attempt 1. These are environmental, not logic, failures.

# Agent Pipeline

The full phase plan lived in `.q-system/agent-pipeline/agents/step-orchestrator.md`
and is retired with the pipeline (decisions.md RULE-2026-08-30-A). That file
stays on disk because `validate-separation.py` and the kipi-mcp validator both
still assert it exists, so deleting it turns `kipi check` red; that is the
separate deliberate act, not this edit. Model allocation for the agents that ARE
live is `.claude/rules/model-allocation.md` (single source; validated by
`kipi check`).

**Full post text rule (ENFORCED):** Agents reading social posts MUST save actual post text, not summaries.

**Content review pipeline:** `/q-market-review` runs 4 Sonnet passes via the content-reviewer agent.

**Fallback:** If the self-healing loop hits its 3-attempt cap, report to founder with diagnostics. Do not attempt monolithic fallback.
