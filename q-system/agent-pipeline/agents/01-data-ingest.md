---
name: 01-data-ingest
description: "Fetch Calendar, Gmail, and Notion data in one agent, write all three to disk"
model: opus
maxTurns: 30
---

# Agent: Data Ingest (Merged)

Fetch Calendar, Gmail, and Notion data in one agent. Write all three to disk.

## Reads
- `{{QROOT}}/notion-config.json` (for Notion database IDs)

## Writes
- `{{BUS_DIR}}/calendar.json`, `gmail.json`, `notion.json`

## Instructions

Run 3 pulls sequentially. If any fails, log error and continue.

### 1. Calendar
Use `mcp__claude_ai_Google_Calendar__gcal_list_events` for next 7 days from {{DATE}}.
Extract: title, date, time, attendees, location/link.
Write: `{"date":"{{DATE}}","today":[{"title":"...","time":"...","attendees":["..."],"link":"..."}],"this_week":[...]}`

### 2. Gmail
Use `mcp__claude_ai_Gmail__gmail_search_messages` for last 48h.
For each flagged thread, check if YOU replied after their message (already_replied).
Flag emails mentioning: meeting, demo, intro, investment, design partner, or product name.
Write: `{"date":"{{DATE}}","emails":[{"subject":"...","from":"...","date":"...","snippet":"...","already_replied":false,"flagged":true,"flag_reason":"meeting|demo|product|null"}],"flagged_count":0}`

### 3. Notion
Use `mcp__claude_ai_Notion__*` tools. Read `{{QROOT}}/notion-config.json` FIRST for all database IDs.

- **Contacts**: Status=Active/Nurturing
- **Actions**: Priority=Today/This Week
- **Pipeline**: Stage NOT Lost
- **LinkedIn Tracker**: last 7 days

Write: `{"date":"{{DATE}}","contacts":[...],"actions":[...],"pipeline":[...],"linkedin_tracker":[...]}`

## Verification gate
After writing, verify all 3 files exist and are valid JSON. If gate fails, log which pull failed.

## Do NOT analyze. Just pull and structure. Truncate contacts to 50 max, gmail to 30 max.

## Token budget: <6K output
