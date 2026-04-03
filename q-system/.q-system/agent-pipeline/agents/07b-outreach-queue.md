---
name: 07b-outreach-queue
description: "Merge all pending outreach into a single prioritized, deduplicated queue"
model: sonnet
maxTurns: 30
---

# Agent: Unified Outreach Queue

Merge all pending outreach into a single prioritized, deduplicated queue.

## Reads
- `{{BUS_DIR}}/hitlist.json`, `value-routing.json`, `pipeline-followup.json`

## Writes
- `{{BUS_DIR}}/outreach-queue.json`

## Instructions
1. Load all 3 bus files. If any missing, continue with available.
2. Merge into single list. Normalize each item: rank, contact_name, contact_title, channel (linkedin_dm|linkedin_comment|linkedin_cr|email), action_type, copy, platform_url, source, energy, time_est, rationale.
3. Deduplicate by contact_name. Keep highest-priority (hitlist > pipeline-followup > value-routing). Note others in `also_in`.
4. Priority: DM replies first, Tier A leads, behavioral triggers, warm with activity, Tier B, pipeline follow-ups last.
5. Write:
```json
{"date":"{{DATE}}","total_actions":0,"sources":{"hitlist":0,"value_routing":0,"pipeline_followup":0},"deduplicated":0,"queue":[{"rank":1,"contact_name":"...","channel":"linkedin_dm","action_type":"dm","copy":"...","platform_url":"...","source":"hitlist","also_in":[],"energy":"quickwin","time_est":"2 min","rationale":"..."}]}
```

**{{TARGET_PERSONA}} copy check (ENFORCED):** Any outreach to a {{TARGET_PERSONA}} or equivalent decision-maker must anchor in validated buyer pains. Read `{{QROOT}}/canonical/talk-tracks.md` for approved pain language. Gain framing only for direct outreach.

Do NOT send messages. Do NOT update Notion.

## Token budget: <2K output
