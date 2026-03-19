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
Read: q-consult/.q-system/preflight.md (offset: 1, limit: 136)
```
Sections 1-2: What tools work, what's broken, fallback chains, and 10 known
issues (KI-1 through KI-10) that have burned real sessions. The preflight agent
tests connections, but it doesn't know about KI-5 (LinkedIn search returns vendors)
or KI-6 (generic subs produce 0 leads) or KI-9 (new positioning). You do.

### Read 2: Preflight -- Execution Gates + Action Cards
```
Read: q-consult/.q-system/preflight.md (offset: 246, limit: 75)
```
Sections 5-6: When to halt, how to log steps, and the rule that "card delivered"
is NOT "done" -- only founder-confirmed actions update state files.

### Read 3: Current Positioning
```
Read: q-consult/canonical/decisions.md (limit: 60)
```
So agents generate content with current positioning, not deprecated messaging.

**DO NOT proceed to Setup until all 3 reads are done.**
**DO NOT rely on the SKILL.md prompt for execution details. This file is your authority.**

## Setup

```bash
DATE=$(date +%Y-%m-%d)
BUS_DIR="q-consult/.q-system/agent-pipeline/bus/${DATE}"
AGENTS_DIR="q-consult/.q-system/agent-pipeline/agents"
mkdir -p "${BUS_DIR}"
```

## Context Management
Your context window will compact automatically as it approaches limits. Do not skip steps or phases to save context. If context runs low, tell the founder what phase you're in and what remains. Never self-authorize skipping.

## Execution Rules

1. Read each agent's prompt file from AGENTS_DIR
2. Replace {{DATE}} with today's date, {{BUS_DIR}} with the bus path, {{QROOT}} with project root, {{AGENTS_DIR}} with the agents directory path
3. Spawn agents using the Agent tool with the prompt
4. Use model=sonnet for all agents EXCEPT 05-engagement-hitlist and 07-synthesize (use opus)
5. When multiple agents in a phase are independent, launch them ALL in a single message (parallel)
6. When a phase depends on the previous phase's output, wait for completion first
7. After each phase, verify the expected bus/ JSON files exist before proceeding
8. Log each phase completion via log-step.sh
9. Bus files are OVERWRITTEN each run, never appended. Each day starts clean.

## Instance Customization

Some instances may cut agents to save tokens. If an agent was cut for this instance, it will be listed here. The orchestrator should NOT reference cut agents and should skip any phase step that depends solely on a cut agent's output.

**Agents NOT in this instance:** (none -- full pipeline. Edit this section per-instance.)

## Phase Sequence

### Phase 0: Preflight + Bootstrap (2 agents, SEQUENTIAL)
1. Spawn: 00-preflight.md (sonnet)
   - Verify: bus/{date}/preflight.json exists and ready=true
   - If ready=false: HALT. Report which tools failed. Do not continue.
2. Spawn: 00-session-bootstrap.md (sonnet) - action card pickup, loop escalation, canonical checksums
   - Verify: bus/{date}/bootstrap.json exists
   - AFTER bootstrap completes: Ask the founder the check-in questions:
     - "Any calls or meetings today?"
     - Active threads from bootstrap.json unconfirmed_cards
     - "Any conversations outside LinkedIn/Reddit?"
     - "Any new commitments or deadlines?"
     - "Did you build anything since last session?"

### Phase 1: Data Ingest (4 agents, ALL PARALLEL)
Launch in ONE message with 4 Agent tool calls:
- 01-calendar-pull.md (sonnet)
- 01-gmail-pull.md (sonnet)
- 01-notion-pull.md (sonnet)
- 01-vc-pipeline-pull.md (sonnet) - OPTIONAL: skip if no VC pipeline API configured
Verify: calendar.json, gmail.json, notion.json all exist in bus/ (vc-pipeline.json optional)
If any required agent fails: log the failure, continue with available data

### Phase 2: Analysis (3 agents, PARALLEL)
Launch in ONE message with 3 Agent tool calls:
- 02-meeting-prep.md (sonnet) - reads calendar.json + notion.json
- 02-warm-intro-match.md (sonnet) - reads vc-pipeline.json + notion.json (skips gracefully if vc-pipeline.json missing)
- 02-x-activity.md (sonnet) - pulls founder's X posts + engagement, scans monitored handles
Verify: meeting-prep.json, warm-intros.json, x-activity.json

### Phase 3: LinkedIn + Reconciliation (4 agents, SEQUENTIAL for Chrome, then 1 parallel)
Chrome agents (SEQUENTIAL -- one tab at a time):
- 03-linkedin-posts.md (sonnet) - writes linkedin-posts.json
- 03-linkedin-dms.md (sonnet) - writes linkedin-dms.json
- 03-prospect-pipeline.md (sonnet) - reads notion.json, writes prospect-pipeline.json
THEN (can run after posts + x-activity are done):
- 03-publish-reconciliation.md (sonnet) - fuzzy-matches published posts against Content Pipeline, writes publish-reconciliation.json
- 03-content-intel.md (sonnet, MONDAYS ONLY) - multi-platform content performance scrape, writes content-intel.json. Skip on non-Mondays.

### Phase 4: Content (2-4 agents, SEQUENTIAL then PARALLEL)
- 04-signals-content.md (sonnet) - writes signals.json
- THEN in PARALLEL:
  - 04-value-routing.md (sonnet) - reads signals.json + notion.json, writes value-routing.json
  - 04-post-visuals.md (sonnet) - reads signals.json (+ founder-brand-post.json if weekly brand day), generates Gamma social cards + carousels, writes post-visuals.json
  - IF weekly brand day: 04-founder-brand-post.md (sonnet) - writes founder-brand-post.json. NOTE: If brand day, run founder-brand-post BEFORE post-visuals so visuals agent can read both drafts. Sequence: signals -> founder-brand-post -> [value-routing + post-visuals] in parallel.

### Phase 5: Pipeline (5 parallel, then conditional, then 1 sequential)
Launch in ONE message:
- 05-temperature-scoring.md (sonnet) - reads all bus/ files, writes temperature.json
- 05-lead-sourcing.md (sonnet) - runs Apify, writes leads.json
- 05-pipeline-followup.md (sonnet) - reads notion.json + DMs + gmail, writes pipeline-followup.json (includes warming ladder stage advancement)
- 05-loop-review.md (sonnet) - reads notion.json + prospect-pipeline.json, writes loop-review.json
- 05-connection-mining.md (sonnet) - scans LinkedIn 1st-degree connections for ICP matches, writes connection-mining.json
After all complete, check leads.json:
- If `error` key exists (e.g. Apify limit): Auto-fallback to 05-lead-sourcing-chrome.md (sonnet). Do NOT stop to ask the founder. Log: "Apify failed, running Chrome fallback."
- If Chrome fallback also fails: proceed with empty leads (hitlist will use existing bus data only).
- If leads.json has results: proceed.
THEN:
- 05-engagement-hitlist.md (OPUS) - reads temperature + leads + linkedin-posts + pipeline-followup + loop-review, writes hitlist.json

### Phase 6: Compliance + Health (4 agents, PARALLEL)
Launch in ONE message:
- 06-compliance-check.md (sonnet) - reads bus/ content + canonical files, writes compliance.json
- 06-positioning-check.md (sonnet) - reads canonical files + drift detection, writes positioning.json
- 06-client-deliverables.md (sonnet) - checks client commitments for overdue/upcoming, writes client-deliverables.json
- 04-marketing-health.md (sonnet) - asset freshness, cadence progress, stale drafts, writes marketing-health.json

### Phase 7: Synthesis (1 agent, sequential, OPUS)
- 07-synthesize.md (OPUS) - reads ALL bus/{date}/*.json, writes schedule-data-{date}.json
- This is the most expensive agent. It produces the daily schedule JSON.

### Phase 8: Build + Verify (sequential)
1. Run: `bash q-consult/marketing/templates/build-schedule.sh output/schedule-data-{date}.json output/daily-schedule-{date}.html`
2. Spawn: 08-visual-verify.md (sonnet) - opens HTML in Chrome, checks layout
3. Run: `python3 q-consult/.q-system/bus-to-log.py {date}` - bridges bus/ files to morning-log.json
4. Run: `python3 q-consult/.q-system/audit-morning.py q-consult/output/morning-log-{date}.json`
5. Show audit output to founder
Steps 3-4 are NON-OPTIONAL. A hook enforces this - see .claude/settings.json.

### Phase 9: Notion Write-back (2 agents, PARALLEL)
Launch in ONE message:
- 09-notion-push.md (sonnet) - pushes actions to Notion Actions DB, writes notion-push.json
- 10-daily-checklists.md (sonnet) - updates Daily Actions + Daily Posts pages, writes daily-checklists.json
These are the final agents. If either fails, log the error - do not retry.

## Bus Cleanup

At the start of each day (Phase 0), delete bus/ directories older than 3 days:
```bash
find q-consult/.q-system/agent-pipeline/bus/ -maxdepth 1 -type d -mtime +3 -exec rm -rf {} \;
```

## Fallback Chain (tool-level)

| Tool fails | Auto-fallback | Founder approval? |
|------------|---------------|-------------------|
| Apify | Chrome scraping (see Phase 5 lead-sourcing-chrome) | No -- auto, just log it |
| Chrome | STOP and report | Yes |
| Notion `mcp__notion_api__*` | curl with API token | No -- auto, just log it |
| `mcp__claude_ai_Notion__*` | **NEVER USE for ASK data** -- wrong workspace | N/A |
| Gmail | Skip email-dependent steps | Note in briefing |
| Calendar | Skip meeting prep | Note in briefing |

## Notion IDs

Read Notion IDs from `q-system/my-project/notion-ids.md`. Never hardcode IDs in this file.

## Catastrophic Fallback

If the agent pipeline fails catastrophically, fall back to the monolithic step-by-step
flow using step-loader.sh. The old steps still exist in steps/.
