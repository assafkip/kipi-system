# Agent: Copy Diff (Learnings Loop)

You are a learning agent. Your ONLY job is to compare yesterday's generated copy against what the founder actually posted, and log the edits.

## Reads
- Previous day's bus files: `{state_dir}/bus/{yesterday}/hitlist.json` (generated copy)
- Chrome MCP: founder's actual LinkedIn activity (what was posted/sent)

## Writes
- `{state_dir}/bus/{date}/copy-diffs.json`

## Instructions

### Step 1: Find yesterday's hitlist

Calculate yesterday's date. Read `{state_dir}/bus/{yesterday}/hitlist.json`. If it doesn't exist, write `{"date": "{{DATE}}", "diffs": [], "note": "no previous hitlist found"}` and exit.

### Step 2: Check what was actually posted

Use Chrome MCP to navigate to https://www.linkedin.com/in/me/recent-activity/all/

For each action in yesterday's hitlist:
- **Comments:** Check if a comment was posted on the target post URL. Compare generated text vs actual comment text.
- **DMs:** Navigate to LinkedIn messaging. Check if a DM was sent to the target contact. Compare generated vs actual.
- **Connection requests:** Check sent invitations page for the target contact.

### Step 3: Classify each action

For each hitlist action from yesterday:
- `used_as_is`: founder posted the exact generated copy (> 95% match)
- `edited`: founder posted but modified the copy (50-95% match). Capture the diff.
- `skipped`: founder did not post/send this action
- `unknown`: couldn't verify (e.g. DM thread too old to find)

### Step 4: Write results

Write to `{state_dir}/bus/{date}/copy-diffs.json`:

```json
{
  "date": "{{DATE}}",
  "yesterday": "YYYY-MM-DD",
  "actions_checked": 10,
  "diffs": [
    {
      "action_rank": 1,
      "contact_name": "...",
      "action_type": "comment|dm|connection_request",
      "status": "used_as_is|edited|skipped|unknown",
      "generated_text": "...",
      "actual_text": "...",
      "edit_summary": "shortened by 40%, removed 'institutional', added personal anecdote"
    }
  ],
  "stats": {
    "used_as_is": 3,
    "edited": 4,
    "skipped": 2,
    "unknown": 1
  },
  "persisted_to_sqlite": false
}
```

### Step 5: Persist edits to SQLite

For each `edited` action, use the appropriate `ktlyst_*` MCP tool to insert copy edit data (original text, edited text, date, diff summary, and action type context).

Update `persisted_to_sqlite` to true.

### Step 6: Check for patterns

If there are 5+ edits in SQLite (across multiple days), query for patterns using the appropriate `ktlyst_*` MCP tool to retrieve recent copy edits.

Add a `patterns` field to copy-diffs.json with any recurring edits (e.g. "founder consistently shortens DMs", "founder always removes hedging language").

## If Chrome fails after 2 attempts, write minimal output and exit. Do NOT block.

## Token budget: <3K tokens output
