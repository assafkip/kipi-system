---
name: 03-dp-pipeline
description: "Read Notion pipeline data, count design partners by status, flag auto-close candidates"
model: opus
maxTurns: 30
---

# Agent: DP Pipeline Check

Read Notion pipeline data, count design partners by status, flag auto-close candidates.

## Reads
- `{{BUS_DIR}}/notion.json`
- `{{AGENTS_DIR}}/_cadence-config.md` for breakup/park threshold

## Writes
- `{{BUS_DIR}}/dp-pipeline.json`

## Instructions
1. Parse notion.json for records with type "Design Partner" or dp_status present
2. Count by bucket: Active, Warm, Cooling, Passed
3. Compute days since last touch (today: {{DATE}})
4. Apply auto-close timing from cadence config
5. Flag `pipeline_below_target: true` if active < target (read from `{{DATA_DIR}}/my-project/current-state.md` for pipeline targets)
6. Write:
```json
{"date":"{{DATE}}","counts":{"active":0,"warm":0,"cooling":0,"passed":0},"pipeline_below_target":false,"target":12,"auto_close_candidates":[],"all_partners":[{"name":"...","status":"...","days_since_last_touch":0}]}
```

Do NOT change Notion. Just read and write.

## Token budget: <2K output
