# Agent Pipeline Orchestrator

Phased morning pipeline. Phase 0 is deterministic Python (zero tokens). Phases 1-5 spawn agents.
Agents read harvest data via `kipi_get_harvest` MCP tool. Analysis agents write to bus/ for downstream consumption.

## Setup

```
AGENTS_DIR="q-system/agent-pipeline/agents"
```

Paths, bus directory creation, and cleanup are handled by `kipi_morning_init`.

## Execution Rules

1. **Read each agent's .md file before spawning.** Use Read tool, extract body after YAML `---`, replace template variables ({{DATE}}, {{BUS_DIR}}, {{CONFIG_DIR}}, {{DATA_DIR}}, {{STATE_DIR}}, {{AGENTS_DIR}}), pass as Agent prompt. Never paraphrase.
2. **Model allocation** — use the `model` field from YAML frontmatter:
   - **haiku**: harvest agents (chrome/mcp prompts), simple checks (00b-energy-check, 03-publish-reconciliation, 04-marketing-health, 05-loop-review, 06-client-deliverables, 07b-outreach-queue, 08-visual-verify, 09-notion-push, 10-daily-checklists)
   - **sonnet**: analysis + content (01c-copy-diff, 01d-graph-kb, 02-x-activity, 02-meeting-prep, 02-warm-intro-match, 03-content-intel, 03d-outbound-detection, 04-founder-brand-post, 04-post-visuals, 04-signals-content, 04-value-routing, 05-connection-mining, 05-lead-sourcing, 05-pipeline-followup, 05-temperature-scoring, 06-compliance-check, 06-positioning-check, 00g-monthly-checks, 00h-memory-review)
   - **opus**: synthesis only (05-engagement-hitlist, 07-synthesize)
3. Launch independent agents in ONE message (parallel). Wait when phase depends on previous output.
4. Log each phase via `log_step` MCP tool.

## Phase Sequence

### Phase 0: Init (deterministic Python — zero tokens)

1. Ask the founder: **"Energy check before we start. 1-5?"** Wait for response.
2. Call `kipi_morning_init` MCP tool with the energy level.
   This single call does ALL of:
   - Creates today's bus directory, cleans old ones (>3 days)
   - Preflight file checks (canonical files, relationships)
   - Session bootstrap (recover action cards, loop stats, stall detection, checksums)
   - Canonical digest (parses all canonical files into structured JSON)
   - Energy compression table
3. Check `result.preflight.ready`. If false → **HALT**. Report which files are missing.
4. Quick MCP tool checks — call `gcal_list_events` and `gmail_search_messages` to verify Google MCP servers respond. If either fails → **HALT**.
5. Store the result. Key fields for downstream agents:
   - `result.canonical_digest` — replaces canonical-digest.json (pass to agents that need it)
   - `result.bootstrap` — action cards, stalls, loop stats
   - `result.energy` — compression table (max_hitlist, skip_deep_focus)

### Phase 0.5: Energy Gate Already Done
Energy is captured in Phase 0. No separate agent needed.

### Phase 0.6: Monthly Checks + Memory Review (conditional)
- IF 1st of month: Spawn 00g-monthly-checks.md (sonnet)
- IF Monday: Spawn 00h-memory-review.md (sonnet)
- If both: launch in ONE message. If neither: skip.

### Phase 1: Data Harvest (1 MCP call + 2 agents, PARALLEL)

1. Call `kipi_harvest` MCP tool with mode="incremental".
   Returns:
   - `python_results`: HTTP/Apify/local sources already fetched and stored in SQLite
   - `chrome_agent_prompt`: prompt for Chrome harvest agent (if chrome sources exist)
   - `mcp_agent_prompt`: prompt for MCP harvest agent (if MCP sources exist)
   - `run_id`: harvest run ID

2. Spawn harvest agents in ONE message (parallel):
   - IF `chrome_agent_prompt` is not null: Spawn Agent with that prompt (haiku, 30 turns)
   - IF `mcp_agent_prompt` is not null: Spawn Agent with that prompt (haiku, 15 turns)
   - Both agents call `kipi_store_harvest` to persist results to SQLite

3. After agents complete, call `kipi_harvest_summary` to verify record counts.
   Log: "Harvest complete: {source}: {count} records" for each source.

### Phase 2: Analysis (5-7 agents, mixed parallel/sequential)

These agents read from `kipi_get_harvest` and write analysis results to bus/:

**Parallel batch 1:**
- 01c-copy-diff.md (sonnet) — compares harvest data vs yesterday's hitlist
- 01d-graph-kb.md (sonnet) — queries relationships from harvest graph data
- 02-x-activity.md (haiku) — ranks X posts from harvest data
- 03d-outbound-detection.md (sonnet) — detects actions from harvest linkedin-outbound
- 03-publish-reconciliation.md (haiku) — matches harvest posts vs pipeline drafts

**Parallel batch 2** (after batch 1 completes — these read batch 1 outputs):
- 02-meeting-prep.md (sonnet) — reads harvest calendar + notion + graph-digest
- 02-warm-intro-match.md (sonnet) — reads harvest vc-pipeline + notion + graph-digest

### Phase 3: Content (2-4 agents, SEQUENTIAL then PARALLEL)
- 04-signals-content.md (sonnet) — writes signals.json
- THEN parallel:
  - 04-value-routing.md (sonnet) — reads signals + harvest notion data
  - 04-post-visuals.md (sonnet) — reads signals, generates visuals
  - IF Wednesday: 04-kipi-promo.md first, THEN post-visuals

### Phase 4: Pipeline (4+ parallel, then 1 sequential)
Launch parallel:
- 05-temperature-scoring.md (sonnet) — reads all bus/ + harvest data
- 05-lead-sourcing.md (sonnet) — reads harvest x-lead-search + reddit-leads, scores leads
- 05-pipeline-followup.md (sonnet) — reads harvest notion + gmail data
- 05-loop-review.md (sonnet) — reads harvest notion data
- IF Monday: 03-content-intel.md (sonnet) — reads harvest data for 5 platforms

THEN sequential:
- 05-engagement-hitlist.md (sonnet) — reads all Phase 4 outputs + harvest data, writes hitlist.json

### Phase 5: Compliance (2 agents, PARALLEL)
- 06-compliance-check.md (sonnet) — reads bus/ content + canonical digest
- 06-positioning-check.md (sonnet) — reads canonical digest

### Phase 6: Synthesis + Queue (sequential)
- 07-synthesize.md (OPUS) — reads ALL bus/ files + harvest data, writes schedule-data-{date}.json
- 07b-outreach-queue.md (sonnet) — merges hitlist + value-routing + pipeline-followup

### Phase 7: Build + Verify (sequential)
1. `kipi_build_schedule` MCP tool → generates HTML from schedule JSON
2. 08-visual-verify.md (sonnet) — opens HTML in Chrome, checks layout
3. `kipi_bus_to_log` MCP tool — bridges bus/ to morning-log.json
4. `kipi_audit_morning` MCP tool — audits the morning log
5. Show audit results to founder. NON-OPTIONAL.

### Phase 8: Notion Write-back (2 agents, PARALLEL)
- 09-notion-push.md (sonnet) — pushes actions to Notion
- 10-daily-checklists.md (sonnet) — updates Daily Actions/Posts pages

## Post-Pipeline
- Call `kipi_backup` MCP tool
- Report backup path to founder
