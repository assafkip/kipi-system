---
name: 03b-linkedin-notifications
description: "Scrape LinkedIn notifications for behavioral signals, write to disk"
model: haiku
maxTurns: 30
---

# Agent: LinkedIn Notifications Pull

Scrape LinkedIn notifications for behavioral signals. Write to disk.

## Reads
- None (fetches live from LinkedIn via Chrome)

## Writes
- `{{BUS_DIR}}/behavioral-signals.json`

## Instructions
1. Chrome MCP: navigate to https://www.linkedin.com/notifications/
2. Scan last 7 days. Extract: post_like (weight 2), post_comment (3), profile_view (2), post_share (3), mention (3).
3. If Chrome fails after 2 attempts, write `{"date":"{{DATE}}","signals":[],"profile_views":[],"error":"chrome_failed"}` and exit.
4. Write:
```json
{"date":"{{DATE}}","signals":[{"contact_name":"...","signal_type":"post_like|post_comment|profile_view|post_share|mention","signal_date":"...","post_url":"...","weight":2}],"profile_views":[{"contact_name":"...","viewed_date":"..."}],"persisted_to_sqlite":false}
```
5. Persist to SQLite: `python3 {{QROOT}}/.q-system/data/db-query.py insert-behavioral-signals {{BUS_DIR}}/behavioral-signals.json`
6. Update persisted_to_sqlite to true if succeeded.

Do NOT generate follow-up copy. Just pull and structure.

## Token budget: <2K output
