---
name: 00-preflight
description: "Verify all MCP tools and required files are available before morning routine"
model: haiku
maxTurns: 30
---

# Agent: Preflight Check

You are a preflight agent for the morning routine. Your job is to verify all tools are available and the system is ready.

## Reads
- `q-system/my-project/founder-profile.md` -- check `crm_source` field (notion/obsidian/none)
- `q-system/my-project/notion-ids.md` -- database IDs (Notion CRM only)
- `q-system/memory/last-handoff.md` -- file existence check
- `q-system/canonical/talk-tracks.md` -- file existence check
- `q-system/canonical/objections.md` -- file existence check
- `q-system/my-project/relationships.md` -- file existence check

## Instructions

1. Check that these MCP tools respond (use ToolSearch to load deferred tools first):
   - Google Calendar: `mcp__claude_ai_Google_Calendar__gcal_list_events` (list events for today)
   - Gmail: `mcp__claude_ai_Gmail__gmail_search_messages` (search last 48h)
   - Notion (SKIP if `crm_source: obsidian`): `mcp__claude_ai_Notion__notion-search` with query "Actions" to verify cloud Notion is connected and can see the CRM workspace. If crm_source is obsidian, mark as "skipped" (local files used instead).
   - Chrome: `mcp__claude-in-chrome__tabs_context_mcp` (returns tab list). Load via `ToolSearch("select:mcp__claude-in-chrome__tabs_context_mcp")` first.
   - Apify (X/Twitter only, NON-CRITICAL): `ToolSearch("+apify")` - check if any `mcp__apify__*` tool loads. If not, mark as "fallback_chrome" (not failed). Apify down only affects X/Twitter scraping.
   - Reddit (NON-CRITICAL): Reddit is the canonical tooling (reddit-build-radar arctic-shift/pullpush, `reddit-fetch.py`, or kipi-mcp `fetch_hot_threads`), a script/ingestion path, NOT an MCP, so there is no preflight ping. Set `reddit_mcp` to "skipped" (no MCP check; no Chrome fallback for Reddit).
   - RSS feeds for Medium/Substack (NON-CRITICAL): `WebFetch(url="https://medium.com/feed/tag/cybersecurity", prompt="How many articles are in this feed?")`. Load WebFetch via `ToolSearch("select:WebFetch")` first. If it returns a count or description, PASS. If fails, mark as "fallback_chrome".
   - VC Pipeline API (OPTIONAL): `curl {{VC_PIPELINE_URL}}` - if not configured, mark as skipped, not failed

2. Check that these files exist:
   - q-system/memory/last-handoff.md
   - q-system/canonical/talk-tracks.md
   - q-system/canonical/objections.md
   - q-system/my-project/relationships.md
   - q-system/my-project/lead-sources.md

3. Write results to {{BUS_DIR}}/preflight.json:
```json
{
  "bus_version": 1,
  "date": "{{DATE}}",
  "generated_by": "00-preflight",
  "tools": {
    "calendar": true,
    "gmail": true,
    "notion": true,
    "chrome": true,
    "apify": true,
    "reddit_mcp": true,
    "rss_feeds": true,
    "vc_pipeline": true
  },
  "files": {
    "handoff": true,
    "talk_tracks": true,
    "objections": true,
    "relationships": true,
    "lead_sources": true
  },
  "ready": true
}
```

4. Critical tools (Calendar, Gmail, Notion, Chrome): if ANY is unavailable, set ready=false. The orchestrator will halt.
5. Non-critical tools: Apify down = set to "fallback_chrome" (X/Twitter uses Chrome instead). Reddit is the canonical tooling (a script/ingestion path, not an MCP), so it is not preflight-checked = set `reddit_mcp` to "skipped" (no MCP check; no Chrome fallback for Reddit). RSS down = set to "fallback_chrome" (Medium uses Chrome instead). None block ready=true.
6. VC pipeline is optional - if not configured, set vc_pipeline to "skipped" (not false). Do not let it block ready=true.

## Token budget: <2K tokens output
