---
name: 01c-copy-diff
description: "Compare yesterday's generated copy against what the founder actually posted, log edits"
model: sonnet
maxTurns: 30
---

# Agent: Copy Diff (Learnings Loop)

Compare yesterday's generated copy against what the founder actually posted. Log edits.

## Reads
- `{{BUS_DIR}}/../{yesterday}/hitlist.json` (generated copy)
- Chrome MCP: founder's actual LinkedIn activity

## Writes
- `{{BUS_DIR}}/copy-diffs.json`

## Instructions

### Step 1: Find yesterday's hitlist
Calculate yesterday's date. Read `{{QROOT}}/.q-system/agent-pipeline/bus/{yesterday}/hitlist.json`. If missing, write `{"date":"{{DATE}}","diffs":[],"note":"no previous hitlist found"}` and exit.

### Step 2: Check what was posted
Use Chrome MCP to check https://www.linkedin.com/in/me/recent-activity/all/ and messaging.
For each hitlist action: check if comment/DM/CR was sent, compare generated vs actual text.

### Step 3: Classify
- `used_as_is`: >95% match
- `edited`: 50-95% match (capture the diff)
- `skipped`: not posted/sent
- `unknown`: couldn't verify

### Step 4: Write
```json
{"date":"{{DATE}}","yesterday":"YYYY-MM-DD","actions_checked":10,"diffs":[{"action_rank":1,"contact_name":"...","action_type":"comment|dm|connection_request","status":"used_as_is|edited|skipped|unknown","edit_summary":"..."}],"stats":{"used_as_is":0,"edited":0,"skipped":0,"unknown":0},"persisted_to_sqlite":false}
```

### Step 5: Persist edits to SQLite
For each `edited` action, insert into `copy_edits` table in `{{QROOT}}/.q-system/data/metrics.db`.

If Chrome fails after 2 attempts, write minimal output and exit. Do NOT block.

## Token budget: <3K output
