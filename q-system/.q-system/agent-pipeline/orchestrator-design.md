# Morning Orchestrator - Agent Tool Design

## How it works

The orchestrator is a set of instructions that Claude Code follows using its native
Agent tool. Each "agent" is a markdown prompt file in `agents/`. Claude Code spawns
them as sub-agents (Sonnet for data pulls, Opus for synthesis).

## Phase execution

```
Phase 0: Preflight (sequential, must pass)
  -> Agent: 00-preflight.md (sonnet)
  -> Writes: bus/{date}/preflight.json
  -> If ready=false, HALT

Phase 1: Data Ingest (parallel - all independent pulls)
  -> Agent: 01-calendar-pull.md (sonnet)     -> bus/{date}/calendar.json
  -> Agent: 01-gmail-pull.md (sonnet)        -> bus/{date}/gmail.json
  -> Agent: 01-notion-pull.md (sonnet)       -> bus/{date}/notion.json
  -> Agent: 01-vc-pipeline-pull.md (sonnet)  -> bus/{date}/pipeline.json
  -> All launched in a single message with multiple Agent tool calls

Phase 2: Analysis (parallel where possible)
  -> Agent: 02-meeting-prep.md (sonnet)      -> bus/{date}/meeting-prep.json
  -> Agent: 02-warm-intro-match.md (sonnet)  -> bus/{date}/warm-intros.json

Phase 3: Social Activity (sequential - browser access needed)
  -> Agent: 03-social-posts.md (sonnet)      -> bus/{date}/social-posts.json
  -> Agent: 03-social-dms.md (sonnet)        -> bus/{date}/social-dms.json
  -> Agent: 03-pipeline-health.md (sonnet)   -> bus/{date}/pipeline-health.json

Phase 4: Content (sequential - routing depends on signals)
  -> Agent: 04-signals-content.md (sonnet)   -> bus/{date}/signals.json
  -> THEN: 04-value-routing.md (sonnet)      -> bus/{date}/value-routing.json

Phase 5: Pipeline & Sourcing (parallel scoring, then sequential)
  -> Agent: 05-temperature-scoring.md (sonnet) -> bus/{date}/temperature.json
  -> Agent: 05-lead-sourcing.md (sonnet)       -> bus/{date}/leads.json
  -> THEN: 05-engagement-hitlist.md (opus)     -> bus/{date}/hitlist.json

Phase 6: Compliance (parallel)
  -> Agent: 06-compliance-check.md (sonnet)    -> bus/{date}/compliance.json
  -> Agent: 06-positioning-check.md (sonnet)   -> bus/{date}/positioning.json

Phase 7: Synthesis (sequential, opus)
  -> Agent: 07-synthesize.md (opus)
  -> Reads ALL bus/{date}/*.json
  -> Writes: output/schedule-data-{date}.json

Phase 8: Build + Verify (sequential)
  -> MCP: kipi_build_schedule (builds HTML from JSON)
  -> Agent: 08-visual-verify.md (sonnet)     -> bus/{date}/visual-verify.json
  -> Bash: audit-morning.py (validates log)
```

## Key rules

1. Each agent prompt includes: what bus/ files to READ, what bus/ file to WRITE
2. Agents that read social posts must save FULL TEXT, never summaries
3. Sonnet for data pulls and checks. Opus only for synthesis and engagement hitlist.
4. If any Phase 0-1 agent fails, HALT everything
5. Phases 2+ can degrade gracefully (log failure, continue)
6. Bus files are JSON. Agents parse JSON in, write JSON out.
7. Bus directories older than 3 days are cleaned in Phase 0

## Token budget estimate

- Each Sonnet agent: ~2-5K tokens
- Opus synthesis: ~10-15K tokens
- Opus hitlist: ~8-12K tokens
- Total: ~60-80K tokens across all agents
- vs monolithic: ~100-150K tokens in one context
- Savings: ~30-50% + better quality per step
