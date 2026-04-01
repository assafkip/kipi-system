---
description: "System health check — verify all dependencies, databases, integrations, and recent run status"
---

# /q-health — System Health Check

Quick diagnostic that verifies the system is ready to run without executing a full /q-morning. Run this when something seems off or after making config changes.

## Process

Run these checks in order. Report results as a clean summary.

### 1. File Health
Call `kipi_preflight` MCP tool. Report:
- Which required files exist and have valid content
- Which files are missing or empty
- Any content_warnings

### 2. Database Health
Call `kipi_morning_init` with energy_level=3 (just for the db_integrity check). Report:
- SQLite integrity: ok/corrupted
- If corrupted: "Database may be damaged. Restore from backup: `kipi_import`"

### 3. MCP Server Connectivity
Test each required MCP server. For each, try a simple call:

| Server | Test Call | Install Command |
|--------|----------|-----------------|
| Google Calendar | `gcal_list_events` | `claude mcp add google-calendar -- npx -y @anthropic/google-calendar-mcp` |
| Gmail | `gmail_search_messages` with query "newer_than:1d" | `claude mcp add gmail -- npx -y @anthropic/gmail-mcp` |
| Chrome | Check if chrome MCP tools are available via ToolSearch | Configured in Claude.ai settings |
| Reddit | `fetch_hot_threads` with any subreddit | `claude mcp add reddit -- uvx --from git+https://github.com/adhikasp/mcp-reddit.git mcp-reddit` |

For each failure, show the install command.

### 4. Last Harvest Status
Call `kipi_harvest_status` MCP tool. Report:
- Last run ID, date, status (complete/partial/failed)
- If partial: which sources failed
- Time since last successful run

### 5. Loop Status
Call `kipi://loops/stats` MCP resource. Report:
- Open loops count and escalation levels
- Any level 3 (14+ day) loops that need attention
- Recently closed loops

### 6. Notion Queue
Call `kipi_get_notion_queue` MCP tool. Report:
- Pending writes awaiting retry
- Failed writes that need manual intervention

### 7. Backup Status
Call `kipi://backups` MCP resource. Report:
- Number of backups
- Most recent backup date and size
- If no backups: "No backups found. Backups are created automatically during /q-morning."

### 8. Source Configuration
Report number of configured harvest sources from `kipi-mcp/sources/`. Note any that are disabled.

## Output Format

```
System Health Report
====================

Files:           OK (3/3 required files present with content)
Database:        OK (integrity check passed)
Google Calendar: OK
Gmail:           OK
Chrome MCP:      NOT CONNECTED — Install: claude mcp add ...
Reddit MCP:      OK
Last Harvest:    2026-04-01 08:15 (complete, 187 records)
Open Loops:      12 open (2 at level 2, 1 at level 3)
Notion Queue:    0 pending
Backups:         5 archives (latest: 2026-04-01, 2.1MB)
Sources:         22 configured (22 enabled)

Issues Found:
- Chrome MCP not connected (required for LinkedIn harvest)
- 1 loop at level 3: DM to John Smith (18 days). Consider force-closing.

Overall: YELLOW — 1 issue needs attention
```

Use OK/WARNING/ERROR for each check. Overall status: GREEN (all ok), YELLOW (warnings), RED (errors).
