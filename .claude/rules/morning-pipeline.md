---
description: Morning routine pipeline execution rules
paths:
  - "q-system/.q-system/**"
  - "q-system/output/**"
---

# Preflight, Fail-Fast, and Audit Harness (ENFORCED)

**Before every `/q-morning` run, read `.q-system/preflight.md` FIRST.** Contains tool manifest, known issues, session budget, step completion log format.

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

Read `.q-system/agent-pipeline/agents/step-orchestrator.md` for the full phase plan. Agents communicate through JSON files in `bus/{date}/`, not context. Model allocation: see `.claude/rules/model-allocation.md` (single source; validated by `kipi check`).

**Full post text rule (ENFORCED):** Agents reading social posts MUST save actual post text, not summaries.

**Content review pipeline:** `/q-market-review` runs 4 Sonnet passes via the content-reviewer agent.

**Fallback:** If the self-healing loop hits its 3-attempt cap, report to founder with diagnostics. Do not attempt monolithic fallback.
