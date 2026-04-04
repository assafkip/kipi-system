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

If any MCP server is unavailable or any step fails, STOP immediately and report. Do NOT continue with partial data.

# Agent Pipeline

Read `.q-system/agent-pipeline/agents/step-orchestrator.md` for the full phase plan. Agents communicate through JSON files in `bus/{date}/`, not context. Model allocation: Haiku for data pulls, scrapes, and simple writes. Sonnet for analysis/content. Opus for engagement hitlist and synthesis only.

**Full post text rule (ENFORCED):** Agents reading social posts MUST save actual post text, not summaries.

**Content review pipeline:** `/q-market-review` runs 4 Sonnet passes via the content-reviewer agent.

**Fallback:** If agent pipeline fails, report to founder with diagnostics. Do not attempt monolithic fallback.
