---
name: morning-orchestrator
description: "Orchestrates the 9-phase morning routine pipeline. Spawns sub-agents per phase, manages bus/ JSON communication, and produces the daily schedule."
model: opus
maxTurns: 200
---

# Agent Pipeline Orchestrator

This step replaces the monolithic morning routine with a phased agent pipeline.
Each phase spawns sub-agents via the Agent tool. Agents communicate through
JSON files in the bus/ directory.

## MANDATORY READS (before Phase 0 -- do not skip)

You are about to execute a 9-phase agent pipeline. Before spawning ANY agent,
read these files. If you feel like you already know what to do from the skill
prompt -- you don't. Every session that skipped these reads re-discovered
known bugs and broke guardrails.

### Read 1: Preflight -- Tool Manifest + Known Issues
```
Read: q-system/.q-system/preflight.md (offset: 1, limit: 136)
```
Sections 1-2: What tools work, what's broken, fallback chains, and 10 known
issues (KI-1 through KI-10) that have burned real sessions. The preflight agent
tests connections, but it doesn't know about KI-5 (LinkedIn search returns vendors)
or KI-6 (generic subs produce 0 leads) or KI-9 (new positioning). You do.

### Read 2: Preflight -- Execution Gates + Action Cards
```
Read: q-system/.q-system/preflight.md (offset: 246, limit: 75)
```
Sections 5-6: When to halt, how to log steps, and the rule that "card delivered"
is NOT "done" -- only founder-confirmed actions update state files.

### Read 3: Current Positioning
```
Read: q-system/canonical/decisions.md (limit: 60)
```
So agents generate content with current positioning, not deprecated messaging.

**DO NOT proceed to Setup until all 3 reads are done.**
**DO NOT rely on the SKILL.md prompt for execution details. This file is your authority.**

## Setup

```bash
DATE=$(date +%Y-%m-%d)
BUS_DIR="q-system/.q-system/agent-pipeline/bus/${DATE}"
AGENTS_DIR="q-system/.q-system/agent-pipeline/agents"
mkdir -p "${BUS_DIR}"
```

## Context Management
Your context window will compact automatically at ~50% capacity (set by session-context.sh). After compaction, the PostCompact hook re-injects: operating mode, open loops, morning pipeline phase progress (which bus files exist), canonical positioning snapshot, and voice reminders. Do not skip steps or phases to save context. If context runs low, tell the founder what phase you're in and what remains. Never self-authorize skipping.

**Token conservation:** Never read agent .md files. Never read bus files for verification (use `test -f`). Never inject voice layers into spawn prompts. Each sub-agent has its own context window and reads its own files.

## Execution Rules

1. Do NOT read agent .md files into orchestrator context. Agents have independent context windows and read their own instructions.
2. Spawn agents using the Agent tool. The spawn prompt for each agent is:
   ```
   Read your instructions from {{AGENTS_DIR}}/{agent-file}. Template vars: DATE={{DATE}}, BUS_DIR={{BUS_DIR}}, QROOT={{QROOT}}, AGENTS_DIR={{AGENTS_DIR}}. If your instructions reference voice or AUDHD skill files, read them yourself from the paths specified. Write output to the bus file specified in your instructions.
   ```
3. Model allocation: haiku for data pulls and simple writes (00-*, 01-*, 03-linkedin-posts, 03-linkedin-dms, 08-visual-verify, 09-notion-push, 10-daily-checklists), sonnet for analysis/content agents, opus for 05-engagement-hitlist only
4. When multiple agents in a phase are independent, launch them ALL in a single message (parallel)
5. When a phase depends on the previous phase's output, wait for completion first
6. After each phase, verify the expected bus/ JSON files exist using `test -f` or `ls`. Do NOT read bus file contents for verification. Only read bus files if: (a) a phase failed and you need to diagnose, (b) Phase 0 preflight ready=true gate check, or (c) collection-gate.json for Phase 1 prompt injection. These are small, justified reads.
7. Log each phase completion via log-step.py
8. Bus files are OVERWRITTEN each run, never appended. Each day starts clean.

## Instance Customization

Some instances may cut agents to save tokens. If an agent was cut for this instance, it will be listed here. The orchestrator should NOT reference cut agents and should skip any phase step that depends solely on a cut agent's output.

**Agents NOT in this instance:** (none -- full pipeline. Edit this section per-instance.)

## Phase Sequence

### Phase 0: Preflight + Bootstrap + Canonical Digest (2 agents + 1 script, SEQUENTIAL)
1. Spawn: 00-preflight.md (haiku)
   - Verify: bus/{date}/preflight.json exists and ready=true
   - If ready=false: HALT. Report which tools failed. Do not continue.
2. Spawn: 00-session-bootstrap.md (haiku) - action card pickup, loop escalation, canonical checksums
   - Verify: bus/{date}/bootstrap.json exists
   - AFTER bootstrap completes: Ask the founder the check-in questions:
     - "Any calls or meetings today?"
     - Active threads from bootstrap.json unconfirmed_cards
     - "Any conversations outside LinkedIn/Reddit?"
     - "Any new commitments or deadlines?"
     - "Did you build anything since last session?"
3. Run SCRIPT (not agent): `python3 {{QROOT}}/.q-system/scripts/canonical-digest.py {date}`
   - Verify: bus/{date}/canonical-digest.json exists
4. Run SCRIPT (not agent): `python3 {{QROOT}}/.q-system/scripts/collection-gate.py {date}`
   - Verify: bus/{date}/collection-gate.json exists
   - This does NOT block the pipeline. All verdicts are advisory.
   - Log the summary (skip/collect counts) for the founder.

### Phase 1: Data Ingest (4 agents + 1 script, PARALLEL agents then script)

**Incremental collection:** Before spawning Phase 1 agents, read bus/{date}/collection-gate.json. For each data-pull agent, append the relevant verdict to its prompt:
```
\n\n## Collection Gate Verdict\n<JSON verdict object for this source>
```
Source keys: calendar -> 01-calendar-pull, gmail -> 01-gmail-pull, notion -> 01-notion-pull.
Same injection for Phase 2 (x-activity -> 02-x-activity), Phase 3 (linkedin-posts -> 03-linkedin-posts, linkedin-dms -> 03-linkedin-dms), Phase 5 (lead-sourcing -> 05-lead-sourcing).
If collection-gate.json is missing or unreadable, skip injection and let agents collect normally.

Launch in ONE message with 4 Agent tool calls:
- 01-calendar-pull.md (haiku)
- 01-gmail-pull.md (haiku)
- 01-notion-pull.md (haiku)
- 01-vc-pipeline-pull.md (haiku) - OPTIONAL: skip if no VC pipeline API configured
Verify: calendar.json, gmail.json, notion.json all exist in bus/ (vc-pipeline.json optional)
If any required agent fails: log the failure, continue with available data
THEN run SCRIPT: `python3 {{QROOT}}/.q-system/scripts/copy-diff.py {date}`
- Reads yesterday's hitlist.json + today's linkedin-posts.json, writes copy-diffs.json
- If Chrome data is needed beyond what linkedin-posts provides, spawn 01c-copy-diff.md agent as fallback

### Phase 2: Analysis (3 agents, PARALLEL)
Launch in ONE message with 3 Agent tool calls:
- 02-meeting-prep.md (sonnet) - reads calendar.json + notion.json
- 02-warm-intro-match.md (sonnet) - reads vc-pipeline.json + notion.json (skips gracefully if vc-pipeline.json missing)
- 02-x-activity.md (sonnet) - pulls founder's X posts + engagement, scans monitored handles
Verify: meeting-prep.json, warm-intros.json, x-activity.json

### Phase 3: LinkedIn + Reconciliation (4 agents, SEQUENTIAL for Chrome, then 1 parallel)
Chrome agents (SEQUENTIAL -- one tab at a time):
- 03-linkedin-posts.md (haiku) - writes linkedin-posts.json
- 03-linkedin-dms.md (haiku) - writes linkedin-dms.json
- 03-prospect-pipeline.md (sonnet) - reads notion.json, writes prospect-pipeline.json
THEN (can run after posts + x-activity are done):
- Run SCRIPT (not agent): `python3 {{QROOT}}/.q-system/scripts/publish-reconciliation.py {date}` - fuzzy-matches published posts against Content Pipeline, writes publish-reconciliation.json
- 03-content-intel.md (sonnet, MONDAYS ONLY) - multi-platform content performance scrape, writes content-intel.json. Skip on non-Mondays.

### Phase 4: Content (2-4 agents, SEQUENTIAL then PARALLEL)
- 04-signals-content.md (sonnet) - writes signals.json
- THEN in PARALLEL:
  - 04-value-routing.md (sonnet) - reads signals.json + notion.json, writes value-routing.json
  - 04-post-visuals.md (sonnet) - reads signals.json (+ founder-brand-post.json if weekly brand day), generates Gamma social cards + carousels, writes post-visuals.json
  - IF weekly brand day: 04-founder-brand-post.md (sonnet) - writes founder-brand-post.json. NOTE: If brand day, run founder-brand-post BEFORE post-visuals so visuals agent can read both drafts. Sequence: signals -> founder-brand-post -> [value-routing + post-visuals] in parallel.

### Phase 5: Pipeline (1 script + 4 agents parallel, then conditional, then 1 sequential)
**GATE: Phase 4 must complete before Phase 5 launches.** 05-pipeline-followup reads signals.json (Phase 4 output).
Run SCRIPT first: `python3 {{QROOT}}/.q-system/scripts/temperature-scoring.py {date}` - writes temperature.json
THEN launch in ONE message:
- 05-lead-sourcing.md (sonnet) - runs Chrome (LinkedIn) + Reddit MCP + RSS (Medium) + Apify (X only), writes leads.json
- 05-pipeline-followup.md (sonnet) - reads notion.json + DMs + gmail, writes pipeline-followup.json (includes warming ladder stage advancement)
- 05-loop-review.md (sonnet) - reads notion.json + prospect-pipeline.json, writes loop-review.json
- 05-connection-mining.md (sonnet) - scans LinkedIn 1st-degree connections for ICP matches, writes connection-mining.json

**NOTE:** lead-sourcing uses Chrome ONLY for LinkedIn search (not Reddit - Reddit uses its own MCP). connection-mining also uses Chrome for LinkedIn People Search. Both use Chrome but at different times within their own execution. The Agent tool runs them as independent sub-agents, each making sequential Chrome calls within their own flow. This is safe as long as Chrome calls don't literally overlap. If Chrome contention occurs, the orchestrator will detect it via errors in leads.json or connection-mining.json and log it.

After all complete, check leads.json:
- Read the `platform_errors` object (if present). Each key is a platform that failed.
  - `linkedin` error (Chrome failed): Log failure, proceed without LinkedIn leads. Do NOT fall back to Chrome agent (Chrome was already primary).
  - `reddit` error (Reddit MCP failed): Skip Reddit leads. Do NOT fall back to Chrome for Reddit. Log: "Reddit MCP failed, skipping Reddit leads."
  - `medium` error (RSS failed): Auto-fallback to 05-lead-sourcing-chrome.md (sonnet) for Medium only. Log: "RSS failed for Medium, running Chrome fallback."
  - `x` error (Apify failed): Auto-fallback to 05-lead-sourcing-chrome.md (sonnet) for X only. Log: "Apify failed, running Chrome fallback for X."
- If `platform_errors` is absent or empty: all platforms succeeded, proceed.
- If Chrome fallback also fails: proceed with whatever leads were collected from other platforms.
- The Chrome fallback agent MERGES its results into the existing leads.json (append to qualified_leads, update run_summary counts, remove the fixed platforms from platform_errors).
THEN:
- 05-engagement-hitlist.md (OPUS) - reads temperature + leads + linkedin-posts + pipeline-followup + loop-review, writes hitlist.json

### Phase 6: Compliance + Health + Sycophancy (1 script + 4 agents, script first then PARALLEL agents)
Run SCRIPT first: `python3 {{QROOT}}/.q-system/scripts/compliance-check.py {date}` - writes compliance.json
THEN launch in ONE message:
- 06-positioning-check.md (sonnet) - reads canonical files + drift detection, writes positioning.json
- 06-client-deliverables.md (sonnet) - checks client commitments for overdue/upcoming, writes client-deliverables.json
- 04-marketing-health.md (sonnet) - asset freshness, cadence progress, stale drafts, writes marketing-health.json
- 06-sycophancy-audit.md (sonnet) - anti-sycophancy check (Chandra et al. 2026). Reads all bus/ + decisions.md + sycophancy-log.json. Writes sycophancy-audit.json. If verdict is "watch" or "alert", synthesizer surfaces it in the schedule. **SKIP CONDITION:** If `my-project/founder-profile.md` contains `sycophancy_audit_enabled: false`, do NOT spawn this agent. Log: "Sycophancy audit: disabled by founder preference."

**Post-phase sycophancy gate (MANDATORY, after verify-bus):**
After Phase 6 verify-bus passes, run the deterministic sycophancy harness:
```bash
python3 {{QROOT}}/.q-system/sycophancy-harness.py {date}
```
- Exit 0: proceed to Phase 7 normally
- Exit 1: proceed to Phase 7, BUT the synthesizer MUST treat sycophancy-audit.json as "alert" regardless of what the agent wrote (harness overrode the agent's verdict in the file)
- Exit 2: log error, proceed (harness failure should not block the pipeline)

The harness independently parses decisions.md to verify the agent's pi calculation. If the agent was sycophantic about its own sycophancy audit, the harness catches it and amends sycophancy-audit.json with a `harness_override` field. The synthesizer reads the amended file.

### Phase 7: Synthesis (1 script, sequential, DETERMINISTIC)
Run SCRIPT (not agent): `python3 {{QROOT}}/.q-system/scripts/synthesize-schedule.py {date}`
- Reads all bus/{date}/*.json files, applies section ordering, friction sorting, todayFocus selection, post visual attachment, sycophancy surfacing, investor update triggers
- Validates output against schedule-data.schema.json
- Writes: output/schedule-data-{date}.json
- Verify: output/schedule-data-{date}.json exists
- If exit code 1 (no bus directory): HALT, report to founder
- If exit code 2 (schema validation failed): HALT, show validation errors to founder, do not proceed to Phase 8
- This replaces the 07-synthesize.md Opus agent. No LLM needed for data assembly.

### Phase 8: Build + Verify (sequential)
1. Run: `python3 {{QROOT}}/marketing/templates/build-schedule.py {{QROOT}}/output/schedule-data-{date}.json {{QROOT}}/output/daily-schedule-{date}.html`
2. Spawn: 08-visual-verify.md (haiku) - opens HTML in Chrome, checks layout
3. Run: `python3 {{QROOT}}/.q-system/bus-to-log.py {date}` - bridges bus/ files to morning-log.json
4. Run: `python3 {{QROOT}}/.q-system/audit-morning.py {{QROOT}}/output/morning-log-{date}.json`
5. Show audit output to founder
Steps 3-4 are NON-OPTIONAL. A hook enforces this - see .claude/settings.json.

### Phase 9: Notion Write-back (2 agents, PARALLEL)
Launch in ONE message:
- 09-notion-push.md (haiku) - pushes actions to Notion Actions DB, writes notion-push.json
- 10-daily-checklists.md (haiku) - updates Daily Actions + Daily Posts pages, writes daily-checklists.json
These are the final agents. If either fails, log the error - do not retry.

## Bus Cleanup

At the start of each day (Phase 0), delete bus/ directories older than 3 days:
```bash
find q-system/.q-system/agent-pipeline/bus/ -maxdepth 1 -type d -mtime +3 -exec rm -rf {} \;
```

## Fallback Chain (tool-level)

| Tool fails | Auto-fallback | Founder approval? |
|------------|---------------|-------------------|
| Chrome (LinkedIn lead sourcing) | Skip LinkedIn leads. No fallback. | No -- just log it |
| Reddit MCP | Skip Reddit scraping. No Chrome fallback. | No -- just log it |
| RSS feeds (Medium) | Chrome scraping via 05-lead-sourcing-chrome | No -- auto, just log it |
| Apify (X/Twitter only) | Chrome scraping via 05-lead-sourcing-chrome | No -- auto, just log it |
| Chrome (DMs, interactive) | STOP and report | Yes |
| Notion `mcp__claude_ai_Notion__*` | STOP and report | Yes |
| Gmail | Skip email-dependent steps | Note in briefing |
| Calendar | Skip meeting prep | Note in briefing |

## Notion IDs

Read Notion IDs from `q-system/my-project/notion-ids.md`. Never hardcode IDs in this file.

## Catastrophic Fallback

If the agent pipeline fails catastrophically, stop and report diagnostics to the founder.
Include which phase failed, the bus files written so far, and the error message.
