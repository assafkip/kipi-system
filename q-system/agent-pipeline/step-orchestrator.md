# Agent Pipeline Orchestrator

Phased morning pipeline. Phase 0 is deterministic Python (zero tokens). Phases 1-8 spawn agents.
Agents read harvest data via `kipi_get_harvest` MCP tool. Analysis agents write to bus/ for downstream consumption.

## Setup

```
AGENTS_DIR="q-system/agent-pipeline/agents"
```

Paths, bus directory creation, and cleanup are handled by `kipi_morning_init`.

## Execution Rules

1. **Read each agent's .md file before spawning.** Use Read tool, extract body after YAML `---`, replace template variables ({{DATE}}, {{BUS_DIR}}, {{CONFIG_DIR}}, {{DATA_DIR}}, {{STATE_DIR}}, {{AGENTS_DIR}}), pass as Agent prompt. Never paraphrase.
2. **Model allocation** -- use the `model` field from YAML frontmatter:
   - **haiku**: harvest agents (chrome/mcp prompts), simple checks (03-publish-reconciliation, 03-prospect-pipeline, 04-marketing-health, 05-loop-review, 06-client-deliverables, 07b-outreach-queue, 08-visual-verify, 09-notion-push, 10-daily-checklists)
   - **sonnet**: analysis + content (01c-copy-diff, 01d-graph-kb, 02-x-activity, 02-meeting-prep, 02-warm-intro-match, 03-content-intel, 03d-outbound-detection, 04-founder-brand-post, 04-post-visuals, 04-signals-content, 04-value-routing, 05-connection-mining, 05-lead-sourcing, 05-pipeline-followup, 05-temperature-scoring, 06-compliance-check, 06-positioning-check, 00g-monthly-checks, 00h-memory-review)
   - **opus**: synthesis only (05-engagement-hitlist, 07-synthesize)
3. Launch independent agents in ONE message (parallel). Wait when phase depends on previous output.
4. Log each phase completion via `log_step` MCP tool with step_id format: `phase_N_description`.
5. **Tool permissions per agent** (principle of least privilege):
   - **Read-only agents** (analysis, scoring, compliance): Read, Glob, Grep, MCP reads only. No Edit, Write, Bash.
     - Applies to: 02-meeting-prep, 02-warm-intro-match, 05-temperature-scoring, 05-loop-review, 06-compliance-check, 06-positioning-check, 00g-monthly-checks, 00h-memory-review, 01d-graph-kb, 03-prospect-pipeline, 04-marketing-health
   - **Read + bus-write agents** (content gen, detection): Read, Glob, Grep, Write (bus/ only), MCP reads.
     - Applies to: 01c-copy-diff, 02-x-activity, 03d-outbound-detection, 03-publish-reconciliation, 04-signals-content, 04-value-routing, 04-post-visuals, 04-founder-brand-post, 05-lead-sourcing, 05-pipeline-followup, 05-engagement-hitlist, 05-connection-mining, 06-client-deliverables, 03-content-intel
   - **Full access agents** (synthesis, build, Notion push): All tools including Bash and MCP writes.
     - Applies to: 07-synthesize, 07b-outreach-queue, 08-visual-verify, 09-notion-push, 10-daily-checklists

## Phase Sequence

### Phase 0: Init (deterministic Python -- zero tokens)

1. Ask the founder: **"Energy check before we start. 1-5?"** Wait for response.
2. Call `kipi_morning_init` MCP tool with the energy level.
   This single call does ALL of:
   - Creates today's bus directory, cleans old ones (>3 days)
   - Preflight file checks (canonical files, relationships)
   - Session bootstrap (recover action cards, loop stats, stall detection, checksums)
   - Canonical digest (parses all canonical files into structured JSON)
   - Energy compression table
3. Check `result.preflight.ready`. If false: **HALT**. Report which files are missing.
4. Quick MCP tool checks -- call `gcal_list_events` and `gmail_search_messages` to verify Google MCP servers respond. If either fails: **HALT**.
5. Log: `log_step(date, "phase_0_init", "done", result_summary)`
6. Store the result. Key fields for downstream agents:
   - `result.canonical_digest` -- structured JSON replacing canonical-digest.json
   - `result.bootstrap` -- action cards, stalls, loop stats
   - `result.energy` -- compression table (max_hitlist, skip_deep_focus)

### Phase 0.6: Monthly Checks + Memory Review (conditional)
- IF 1st of month: Spawn 00g-monthly-checks.md (sonnet)
- IF Monday: Spawn 00h-memory-review.md (sonnet)
- If both: launch in ONE message. If neither: skip.
- Log: `log_step(date, "phase_0.6_monthly", "done|skipped")`

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
4. Log: `log_step(date, "phase_1_harvest", "done", "{source}: {count} records")`

### Phase 2: Analysis (5-7 agents, mixed parallel/sequential)

These agents read from `kipi_get_harvest` and write analysis results to bus/:

**Parallel batch 1:**
- 01c-copy-diff.md (sonnet) -- compares harvest data vs yesterday's hitlist
- 01d-graph-kb.md (sonnet) -- queries relationships from harvest graph data
- 02-x-activity.md (haiku) -- ranks X posts from harvest data
- 03d-outbound-detection.md (sonnet) -- detects actions from harvest linkedin-outbound
- 03-publish-reconciliation.md (haiku) -- matches harvest posts vs pipeline drafts

**Parallel batch 2** (after batch 1 -- these read batch 1 outputs):
- 02-meeting-prep.md (sonnet) -- reads harvest calendar + notion + graph-digest
- 02-warm-intro-match.md (sonnet) -- reads harvest vc-pipeline + notion + graph-digest

Log: `log_step(date, "phase_2_analysis", "done")`

### Phase 3: Content (3-5 agents, SEQUENTIAL then PARALLEL)
- 04-signals-content.md (sonnet) -- writes signals.json
- THEN parallel:
  - 04-value-routing.md (sonnet) -- reads signals + harvest notion data
  - 04-post-visuals.md (sonnet) -- reads signals, generates visuals
  - 04-marketing-health.md (haiku) -- checks asset freshness, cadence progress
  - IF Wednesday: 04-founder-brand-post.md (sonnet) -- weekly founder brand post

Log: `log_step(date, "phase_3_content", "done")`

### Phase 4: Pipeline (5-7 parallel, then 1 sequential)
Launch parallel:
- 05-temperature-scoring.md (sonnet) -- reads all bus/ + harvest data
- 05-lead-sourcing.md (sonnet) -- reads harvest x-lead-search + reddit-leads, scores leads
- 05-pipeline-followup.md (sonnet) -- reads harvest notion + gmail data
- 05-loop-review.md (haiku) -- reads harvest notion data
- 03-prospect-pipeline.md (haiku) -- counts prospects by status, pipeline health
- 05-connection-mining.md (sonnet) -- scans LinkedIn connections for ICP matches
- IF Monday: 03-content-intel.md (sonnet) -- reads harvest data for 5 platforms

THEN sequential:
- 05-engagement-hitlist.md (opus) -- reads all Phase 4 outputs + harvest data, writes hitlist.json

Log: `log_step(date, "phase_4_pipeline", "done")`

### Phase 5: Compliance (3 agents, PARALLEL)
- 06-compliance-check.md (sonnet) -- reads bus/ content + canonical digest
- 06-positioning-check.md (sonnet) -- reads canonical digest
- 06-client-deliverables.md (haiku) -- checks upcoming/overdue client commitments

Log: `log_step(date, "phase_5_compliance", "done")`

### Phase 6: Synthesis + Queue (sequential)
- 07-synthesize.md (OPUS) -- reads ALL bus/ files + harvest data, writes schedule-data-{date}.json
- 07b-outreach-queue.md (sonnet) -- merges hitlist + value-routing + pipeline-followup

Log: `log_step(date, "phase_6_synthesis", "done")`

### Phase 7: Build + Verify (sequential)
1. `kipi_build_schedule` MCP tool -- generates HTML from schedule JSON
2. 08-visual-verify.md (sonnet) -- opens HTML in Chrome, checks layout
3. `kipi_bus_to_log` MCP tool -- bridges bus/ to morning-log.json
4. `kipi_audit_morning` MCP tool -- audits the morning log
5. Show audit results to founder. NON-OPTIONAL.

Log: `log_step(date, "phase_7_build", "done")`

### Phase 8: Notion Write-back (2 agents, PARALLEL)
- 09-notion-push.md (sonnet) -- pushes actions to Notion
- 10-daily-checklists.md (sonnet) -- updates Daily Actions/Posts pages

Log: `log_step(date, "phase_8_notion", "done")`

## Post-Pipeline
- Call `kipi_backup` MCP tool
- Report backup path to founder
