# Agent Pipeline Orchestrator

This step replaces the monolithic morning routine with a phased agent pipeline.
Each phase spawns sub-agents via the Agent tool. Agents communicate through
JSON files in the bus/ directory.

## Setup

```bash
DATE=$(date +%Y-%m-%d)
BUS_DIR="q-system/.q-system/agent-pipeline/bus/${DATE}"
AGENTS_DIR="q-system/.q-system/agent-pipeline/agents"
mkdir -p "${BUS_DIR}"
```

## Context Management
Your context window will compact automatically as it approaches limits. Do not skip steps or phases to save context. If context runs low, tell the founder what phase you're in and what remains. Never self-authorize skipping.

## Execution Rules

1. **Read each agent's .md file from AGENTS_DIR before spawning it. This is NON-NEGOTIABLE.**
   - Use the Read tool to load the file
   - Extract the body (everything after the YAML frontmatter closing `---`)
   - Replace template variables: {{DATE}}, {{BUS_DIR}}, {{QROOT}}, {{AGENTS_DIR}}
   - Pass the substituted body as the Agent tool's `prompt` parameter
   - NEVER paraphrase, summarize, or rewrite agent instructions from memory
   - Read on-demand (when about to spawn), not upfront. File content falls out of context after launch.
   - Why: The Agent tool prompt is the ONLY channel to sub-agents. They inherit nothing from the orchestrator. Whatever you write IS their entire world. Paraphrasing causes silent failures.
2. Use model=sonnet for all agents EXCEPT 07-synthesize (use opus). Hitlist was downgraded from Opus to Sonnet.
3. When multiple agents in a phase are independent, launch them ALL in a single message (parallel)
4. When a phase depends on the previous phase's output, wait for completion first
5. After each phase, verify the expected bus/ JSON files exist before proceeding
6. Log each phase completion via the `log_step` MCP tool
7. Bus files are OVERWRITTEN each run, never appended. Each day starts clean.
8. **Tool permissions per agent** (principle of least privilege):
   - **Read-only agents** (analysis, scoring, compliance): Read, Glob, Grep only. No Edit, Write, Bash, or MCP writes.
     - Applies to: 02-meeting-prep, 02-warm-intro-match, 05-temperature-scoring, 05-loop-review, 06-compliance-check, 06-positioning-check
   - **Read + bus-write agents** (data pulls, content gen): Read, Glob, Grep, Write (bus/ only). MCP reads allowed.
     - Applies to: 00-preflight, 00b-energy-check, 01-*, 03-*, 04-*, 05-lead-sourcing, 05-pipeline-followup, 05-engagement-hitlist
   - **Full access agents** (synthesis, build, Notion push): All tools including Bash and MCP writes.
     - Applies to: 07-synthesize, 08-visual-verify, 09-notion-push, 10-daily-checklists
   - When spawning an Agent, do NOT pass disallowed tools. If an agent attempts a write outside its scope, the orchestrator should flag it in the audit log.

## Phase Sequence

### Phase 0: Preflight (1 agent, sequential, MUST PASS)
- Spawn: 00-preflight.md (sonnet)
- Verify: bus/{date}/preflight.json exists and ready=true
- If ready=false: HALT. Report which tools failed. Do not continue.

### Phase 0.5: Energy Check-in (1 agent, sequential, MUST PASS)
- Spawn: 00b-energy-check.md (sonnet)
- This agent asks the founder "Energy check before we start. 1-5?" and waits for a response
- Verify: bus/{date}/energy.json exists
- The compression table in energy.json governs the rest of the routine:
  - Level 1-2: Hitlist capped at 3-5 actions, Deep Focus tasks skipped, quick wins only
  - Level 3: Normal load, moderate hitlist (10 actions)
  - Level 4-5: Full routine, no compression
- ALL downstream agents that produce actionable output MUST read energy.json and respect compression limits
- Key consumers: 05-engagement-hitlist.md, 07-synthesize.md

### Phase 0.7: Canonical Digest (1 agent, sequential, MUST COMPLETE)
- Spawn: 00c-canonical-digest.md (sonnet)
- This agent reads ALL canonical files (1,536 lines, ~20K tokens) ONCE and produces a 2K JSON digest.
- All downstream agents read `canonical-digest.json` instead of the full files. This saves 40-60K tokens per run.
- Verify: `python3 q-system/.q-system/verify-bus.py {date} 1` (checks canonical-digest.json structure)
- If the digest is missing or malformed, downstream agents fall back to reading canonical files directly.

### Phase 1: Data Ingest (4 agents, ALL PARALLEL)
Before spawning: check if bus/{date}/ already contains calendar.json, gmail.json, notion.json from a pre-fetch run. If all exist and are < 2 hours old, skip Phase 1 and log "pre-fetched."
Launch in ONE message with 4 Agent tool calls:
- 01-data-ingest.md (sonnet) - MERGED agent: pulls Calendar + Gmail + Notion in one agent. Writes calendar.json, gmail.json, notion.json. Has built-in verification gate. Saves ~15-20K tokens vs 3 separate agents.
- 01-vc-pipeline-pull.md (sonnet) - separate because it's a different API (localhost:5050)
- 01b-content-metrics.md (sonnet) - Chrome scrapes LinkedIn analytics, writes content-metrics.json + SQLite
- 01c-copy-diff.md (sonnet) - compares yesterday's hitlist copy vs actual posts (Chrome), writes copy-diffs.json + SQLite
Verify: `python3 q-system/.q-system/verify-bus.py {date} 1`
If any fails: log the failure, continue with available data

### Phase 2: Analysis (2 agents, PARALLEL)
Launch in ONE message with 2 Agent tool calls:
- 02-meeting-prep.md (sonnet) - reads calendar.json + notion.json
- 02-warm-intro-match.md (sonnet) - reads vc-pipeline.json + notion.json
Verify: `python3 q-system/.q-system/verify-bus.py {date} 2`

### Phase 3: LinkedIn (5 agents, SEQUENTIAL - Chrome needs one tab at a time)
- 03-linkedin-posts.md (sonnet) - writes linkedin-posts.json
- 03b-linkedin-notifications.md (sonnet) - scrapes linkedin.com/notifications for likes/views/comments/shares, writes behavioral-signals.json + persists to SQLite
- 03-linkedin-dms.md (sonnet) - writes linkedin-dms.json
- 03c-prospect-activity.md (sonnet) - visits top 10 Hot+Warm prospect profiles, pulls their last 2 posts, writes prospect-activity.json. **ENERGY GATE: skip if energy < 3.** Takes ~6 min Chrome time. Rotates via SQLite (skips anyone checked in last 2 days).
- 03-dp-pipeline.md (sonnet) - reads notion.json, writes dp-pipeline.json (no Chrome needed, can overlap)
Verify: `python3 q-system/.q-system/verify-bus.py {date} 3`

### Phase 4: Content (2-4 agents, SEQUENTIAL then PARALLEL)
- 04-signals-content.md (sonnet) - writes signals.json
- THEN in PARALLEL:
  - 04-value-routing.md (sonnet) - reads signals.json + notion.json, writes value-routing.json
  - 04-post-visuals.md (sonnet) - reads signals.json (+ kipi-promo.json if Wednesday), generates Gamma social cards + carousels, writes post-visuals.json
  - IF Wednesday: 04-kipi-promo.md (sonnet) - writes kipi-promo.json. NOTE: If Wednesday, run kipi-promo BEFORE post-visuals so visuals agent can read both drafts. Sequence: signals -> kipi-promo -> [value-routing + post-visuals] in parallel.

### Phase 5: Pipeline (4 parallel, then conditional, then 1 sequential)
Launch in ONE message:
- 05-temperature-scoring.md (sonnet) - reads all bus/ files, writes temperature.json
- 05-lead-sourcing.md (sonnet) - runs Apify, writes leads.json
- 05-pipeline-followup.md (sonnet) - reads notion.json + DMs + gmail, writes pipeline-followup.json
- 05-loop-review.md (sonnet) - reads notion.json + dp-pipeline.json, writes loop-review.json
After all complete, check leads.json:
- If `error` key exists (e.g. Apify limit): Auto-fallback to 05-lead-sourcing-chrome.md (sonnet). Do NOT stop to ask the founder. Log: "Apify failed, running Chrome fallback."
- If Chrome fallback also fails: proceed with empty leads (hitlist will use existing bus data only).
- If leads.json has results: proceed.
Verify: `python3 q-system/.q-system/verify-bus.py {date} 5` (before hitlist, after parallel agents)
THEN:
- 05-engagement-hitlist.md (sonnet) - reads temperature + leads + linkedin-posts + behavioral-signals + prospect-activity + pipeline-followup + loop-review + copy-diffs, writes hitlist.json. Downgraded from Opus to Sonnet (token savings). The behavioral signals and copy learnings provide enough context that Sonnet produces equivalent quality.

### Phase 6: Compliance (2 agents, PARALLEL)
Launch in ONE message:
- 06-compliance-check.md (sonnet) - reads bus/ content + canonical files, writes compliance.json
- 06-positioning-check.md (sonnet) - reads canonical files, writes positioning.json

### Phase 7: Synthesis + Queue (sequential)
- 07-synthesize.md (OPUS) - reads ALL bus/{date}/*.json, writes schedule-data-{date}.json
- This is the most expensive agent. It produces the daily schedule JSON.
- THEN: 07b-outreach-queue.md (sonnet) - merges hitlist + value-routing + pipeline-followup into single outreach-queue.json. Deduplicates by contact. This feeds Phase 9 Notion push.

### Phase 8: Build + Verify (sequential)
1. Run: Use the `build_schedule` MCP tool with json_path="output/schedule-data-{date}.json" and html_path="output/daily-schedule-{date}.html"
2. Spawn: 08-visual-verify.md (sonnet) - opens HTML in Chrome, checks layout
3. Run: `python3 q-system/.q-system/bus-to-log.py {date}` - bridges bus/ files to morning-log.json
4. Run: `python3 q-system/.q-system/audit-morning.py q-system/output/morning-log-{date}.json`
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
find q-system/.q-system/agent-pipeline/bus/ -maxdepth 1 -type d -mtime +3 -exec rm -rf {} \;
```

## Fallback

If the agent pipeline fails catastrophically, fall back to the monolithic step-by-step
flow using the `load_step` MCP tool. The old steps still exist in steps/.
