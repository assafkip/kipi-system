**Step 0f - Connection check sequence (run ALL in parallel where possible):**

| # | Server | Exact Test | Pass Criteria | Required for |
|---|--------|-----------|--------------|-------------|
| 1 | Google Calendar | `mcp__claude_ai_Google_Calendar__gcal_list_events` with today's date | Returns events array (even if empty) | Step 1 calendar, meeting prep |
| 2 | Gmail | `mcp__claude_ai_Gmail__gmail_search_messages` with `q: "after:YYYY/M/D"` (yesterday) | Returns messages array | Step 1 email pull, reply detection |
| 3 | Notion (API) | `mcp__notion_api__API-post-database-query` on Actions DB (ID from `my-project/notion-ids.md`) with `page_size: 1` | Returns results array | Steps 1-10 (CRM, pipeline, tracker, actions) |
| 4 | Chrome | `mcp__claude-in-chrome__tabs_context_mcp` | Returns tab list | Steps 3.8, 5, 5.5 (DMs, GA, LinkedIn) |
| 5 | Apify (MCP) | Any `mcp__apify__*` tool call | Returns response | Steps 2, 5.9 (profile scraping, lead sourcing) |
| 5b | Apify (REST fallback) | `curl -s "https://api.apify.com/v2/acts?token=$APIFY_TOKEN&limit=1"` via Bash | Returns JSON with `data` array | Fallback if MCP Apify unavailable |
| 6 | VC Pipeline API | `curl -s http://localhost:5050/api/pipeline` via Bash | Returns JSON pipeline data | Steps 1, 1.5 (warm intro matching) |
| 7 | NotebookLM | `mcp__notebooklm__list_notebooks` | Returns notebook list | Research grounding (Step 2) |

**Output format (ALWAYS shown, even when all pass):**

```
CONNECTION CHECK (Step 0f)

[PASS] Google Calendar - events loaded
[PASS] Gmail - messages loaded
[PASS] Notion API - Actions DB accessible
[PASS] Chrome - browser connected
[PASS] Apify MCP - tools loaded
[PASS] VC Pipeline API - pipeline data loaded
[PASS] NotebookLM - notebooks accessible

All 7 connections OK. Proceeding to Step 0a.
```

**If ANY fails:**

```
MORNING ROUTINE HALTED - CONNECTION CHECK FAILED

[PASS] Google Calendar - events loaded
[PASS] Gmail - messages loaded
[FAIL] Notion API - Error: "Could not find property..."
[SKIP] Chrome - not tested (halted)
[SKIP] Apify - not tested (halted)
[SKIP] VC Pipeline API - not tested (halted)
[SKIP] NotebookLM - not tested (halted)

Failed: Notion API
Error: [exact error message]
Steps blocked: 1 (actions pull), 3.5 (DP pipeline), 5.8 (temperature scoring), 5.9 (lead gen Phase 4), 9 (action push), 10 (daily checklists)

Fix the issue and re-run /q-morning. Do NOT proceed with partial data.
```

**Degraded mode (optional, founder must explicitly approve):**

If a non-critical server fails (NotebookLM, VC Pipeline API), Claude MAY ask:
"[Server] is down. This blocks [steps]. The rest of the routine can run without it. Proceed without [server], or fix and re-run?"

If the founder says proceed, note the skipped steps in the briefing output. Critical servers (Calendar, Gmail, Notion, Chrome, Apify) have NO degraded mode - they halt the routine.

**This also applies to failures MID-ROUTINE.** If any step fails during execution (API error, timeout, unexpected response, tool call rejected), STOP at that point and report:
```
MORNING ROUTINE HALTED AT STEP [X]

What failed: [description of what was attempted]
Error: [exact error message]
Steps completed: [list of steps that finished successfully]
Steps not run: [list of remaining steps]
Data collected so far: [summary of what was gathered before failure]

Fix the issue and re-run /q-morning.
```

**No partial briefings.** No silent skipping. No substituting missing data. Either the full routine completes or it stops and reports. The founder should never act on incomplete data.

---

### Decision origin tagging:

> Every decision in decisions.md gets an origin tag showing who made it.

**Tags (ENFORCED on all new RULE entries):**
- `[USER-DIRECTED]` - founder explicitly made this decision
- `[CLAUDE-RECOMMENDED -> APPROVED]` - Claude suggested, founder approved
- `[CLAUDE-RECOMMENDED -> MODIFIED]` - Claude suggested, founder changed
- `[CLAUDE-RECOMMENDED -> REJECTED]` - Claude suggested, founder rejected
- `[SYSTEM-INFERRED]` - Claude made this autonomously based on existing rules

**Monthly audit (1st of month, during morning routine):**
- Count decisions by origin tag
- If >60% are rubber-stamped (`APPROVED` with no modification), surface: "Most suggestions are being approved without changes. Either well-calibrated or not being reviewed closely."
- Log audit to `memory/monthly/decision-audit-YYYY-MM.md`

All existing rules in decisions.md are retroactively tagged `[USER-DIRECTED]` since they came from founder directives.
