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
- `edited`: 50-95% match (capture the diff AND the full original + posted text)
- `skipped`: not posted/sent
- `unknown`: couldn't verify

### Step 4: Write
For `edited` status, include `original_text` (yesterday's drafted copy) and `posted_text` (what the founder actually posted). The full-text pair feeds route-overrides-to-learn.py, which builds inbox files for the learn-from-correction skill. `edit_summary` stays as a short human-readable note.

```json
{"date":"{{DATE}}","yesterday":"YYYY-MM-DD","actions_checked":10,"diffs":[{"action_rank":1,"contact_name":"...","action_type":"comment|dm|connection_request","status":"edited","edit_summary":"shortened, removed CTA","original_text":"<full drafted text>","posted_text":"<full posted text>"}],"stats":{"used_as_is":0,"edited":0,"skipped":0,"unknown":0},"persisted_to_sqlite":false}
```

For non-`edited` statuses, omit `original_text` and `posted_text` (they only carry information when an override exists).

### Step 5: Persist edits to SQLite
For each `edited` action, insert into `copy_edits` table in `{{QROOT}}/.q-system/data/metrics.db`. Required columns: `date`, `contact_name`, `action_type`, `original` (full drafted text), `edited` (full posted text), `edit_summary`. The full-text pair is what route-overrides-to-learn.py reads from to build learn-from-correction inputs.

If Chrome fails after 2 attempts, write minimal output and exit. Do NOT block.

## Token budget: <3K output
