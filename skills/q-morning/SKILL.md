---
description: "Daily morning briefing — deterministic init + harvest + agent pipeline producing a copy-paste-ready HTML schedule"
---

# /q-morning — Daily morning briefing

Runs the morning pipeline: deterministic Python init, data harvest, analysis agents, synthesis, and schedule build.

## Setup guard

**FIRST:** Read the `kipi://status` MCP resource.
If `setup_needed` is true: STOP. Tell the user to run `/q-setup` first.

## Path resolution

Read the `kipi://paths` MCP resource to get resolved directories.

## Process

1. **Ask energy level.** "Energy check before we start. 1-5?" Wait for response.

2. **Call `kipi_morning_init`** MCP tool with the energy level.
   This does preflight checks, session recovery, canonical digest, and bus setup — all in Python, zero agent tokens.
   - If `result.preflight.ready` is false → **STOP.** Report which files are missing.
   - Show the founder: loop stats, stalls, recovered action cards (from `result.bootstrap`).

3. **Quick MCP checks.** Call `gcal_list_events` and `gmail_search_messages`. If either fails → **STOP.**

4. **Read step-orchestrator.md** — `q-system/agent-pipeline/step-orchestrator.md`. Follow Phase 1 onward.

5. **Call `kipi_harvest`** MCP tool. This runs all Python data sources (HTTP, Apify, local) and returns prompts for Chrome + MCP harvest agents.

6. **Spawn harvest agents** from the prompts returned by `kipi_harvest` (parallel, haiku).

7. **Run analysis + processing phases** per step-orchestrator.md (Phases 2-6).

8. **Synthesis** — 07-synthesize (opus) produces the daily schedule JSON.

9. **Build HTML** via `kipi_build_schedule` MCP tool.

10. **Audit** via `kipi_bus_to_log` then `kipi_audit_morning`. Show results. NON-OPTIONAL.

11. **Backup** via `kipi_backup`. Report archive path.

## Model allocation

- **Zero tokens:** Preflight, bootstrap, canonical digest, data harvest (Python sources)
- **Haiku:** Harvest agents (Chrome + MCP), simple processing agents
- **Sonnet:** Analysis, content generation, compliance
- **Opus:** Engagement hitlist + synthesis ONLY

## Output rules

- Apply `founder-voice` rule to all written output
- Apply `audhd-executive-function` rule if enabled
- Schedule HTML generated ONLY via `kipi_build_schedule` from JSON data
- Full post text rule: agents MUST preserve actual post text, not summaries

## MCP tools used

`kipi_morning_init`, `kipi_harvest`, `kipi_get_harvest`, `kipi_store_harvest`, `kipi_harvest_summary`,
`log_init`, `log_step`, `log_add_card`, `log_deliver_cards`, `log_gate_check`, `log_checksum`, `log_verify`,
`loop_escalate`, `kipi://loops/open`, `kipi://loops/stats`,
`kipi_build_schedule`, `kipi_bus_to_log`, `kipi_audit_morning`, `kipi_backup`
