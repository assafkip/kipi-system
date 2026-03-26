---
name: 03c-prospect-activity
description: "Check top prospects' recent LinkedIn activity, write to disk"
model: opus
maxTurns: 30
---

# Agent: Prospect Activity Feed

Check top prospects' recent LinkedIn activity. Write to disk.

## Reads
- `{{BUS_DIR}}/notion.json` (top contacts by stage), `linkedin-dms.json` (fallback contacts)

## Writes
- `{{BUS_DIR}}/prospect-activity.json`

## Energy gate: Skip if energy.json level < 3. Takes ~6 min Chrome time.

## Instructions

### Step 1: Pick top 10 prospects
From notion.json: Stage = Active/Warm/Nurturing, sorted by most recent Last Contact. If few contacts, use DM contacts from linkedin-dms.json.

Rotation: check SQLite for recently scanned (last 2 days):
```bash
python3 -c "import sqlite3,json; db=sqlite3.connect('{{QROOT}}/.q-system/data/metrics.db'); print(json.dumps([r[0] for r in db.execute('SELECT DISTINCT contact_name FROM behavioral_signals WHERE signal_date >= date(\"now\",\"-2 days\") AND source=\"prospect_activity_scan\"').fetchall()])); db.close()"
```
Skip anyone returned.

### Step 2: Scrape via Chrome
For each prospect (max 10): navigate to their LinkedIn profile, click Activity/Posts tab, pull last 2 posts (14 days). Save FULL text, post_date, likes, comments, post_url, relevance note.

### Step 3: Write
```json
{"date":"{{DATE}}","prospects_checked":10,"skipped_recent":[],"activity":[{"contact_name":"...","profile_url":"...","posts":[{"post_date":"...","full_post_text":"FULL TEXT","post_url":"...","like_count":0,"comment_count":0,"relevance":"..."}]}]}
```

### Step 4: Log to SQLite for rotation
Insert prospect names into behavioral_signals with source="prospect_activity_scan".

## Token budget: <4K output
