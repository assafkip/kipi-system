# Morning Routine Preflight & Execution Harness

> This file is the single source of truth for what tools are available, what's broken, how to recover, and whether the routine actually completed. Read this BEFORE commands.md on every `/q-morning` run.

---

## 1. Tool Manifest

Every tool the morning routine depends on, its exact test, known limitations, and what to do when it fails.

### Critical (halt if unavailable)

| Tool | Test Command | Pass Criteria | Known Limitations | Fallback |
|------|-------------|---------------|-------------------|----------|
| **Google Calendar** | `mcp__claude_ai_Google_Calendar__gcal_list_events` with `timeMin=today 00:00`, `timeMax=today+7 23:59` | Returns `events` array (even if empty) | None known | None. Halt. |
| **Gmail** | `mcp__claude_ai_Gmail__gmail_search_messages` with `q: "after:YYYY/M/D"` (yesterday) | Returns `messages` array | None known | None. Halt. |
| **Notion API** | `mcp__notion_api__API-post-database-query` on Contacts DB `cabba10d-cd5d-4cff-b042-3241a2be18b5` with `page_size: 1` | Returns `results` array | **`API-patch-page` only updates `title` property.** Cannot update Role, Company, Status, DP Status, Last Contact, What They Care About, Strategic Value, Follow-up Action, Pushback, Email, or any other field. For full property updates, use `mcp__claude_ai_Notion__notion-update-page` IF the workspace matches (see known issues). | None for reads. For writes, see Known Issues #1. |
| **Chrome** | `mcp__claude-in-chrome__tabs_context_mcp` | Returns tab list | Alerts/dialogs block all further commands. Avoid triggering them. | None. Halt. |
| **Apify** | Check if any `mcp__apify__*` tool is available via ToolSearch. If not, test REST: `curl -s "https://api.apify.com/v2/acts?token=$APIFY_TOKEN&limit=1"` | MCP: tool schema returned. REST: JSON with `data` array. | MCP tools sometimes don't load in a session. REST API always works. Token in settings.json: `YOUR_APIFY_TOKEN` | **REST API fallback.** All actors callable via `curl -X POST "https://api.apify.com/v2/acts/ACTOR_ID/runs?token=$APIFY_TOKEN&waitForFinish=120"`. Confirmed working actors listed below. |

### Non-Critical (ask founder before proceeding without)

| Tool | Test Command | Pass Criteria | Known Limitations | Fallback |
|------|-------------|---------------|-------------------|----------|
| **VC Pipeline API** | `curl -s http://localhost:5050/api/pipeline` via Bash | Returns JSON with pipeline data | Must be running locally. Founder needs to start the local pipeline server. | Skip Steps 1.5 (warm intro matching). Note in briefing. |
| **NotebookLM** | `mcp__notebooklm__list_notebooks` | Returns notebook list | Session-based, may need re-auth. | Skip deep research in Step 2. Use Apify for profile data instead. |

### Confirmed Working Apify Actors (validated Mar 10-11, 2026)

| Actor | Input Format | Notes |
|-------|-------------|-------|
| `supreme_coder~linkedin-post` | `{"urls": ["https://www.linkedin.com/search/results/content/?keywords=ENCODED_QUERY&sortBy=date_posted"], "deepScrape": false, "maxItems": 10}` | Field is `urls` NOT `searchUrl`. `sortBy=date_posted` no quotes around value. |
| `trudax~reddit-scraper-lite` | `{"startUrls": [{"url": "https://www.reddit.com/r/SUBREDDIT/search/?q=QUERY&sort=new&restrict_sr=on&t=month"}], "maxItems": 10}` | `restrict_sr=on` REQUIRED. Auth: Bearer token header, NOT query param. |
| `apidojo~tweet-scraper` | Profile mode: pull recent tweets from handles. Search mode: works but limited. | Monitored handles: @BushidoToken, @clintgibler, @RyanGCox_, @obadiahbridges |
| `apify~google-search-scraper` | `{"queries": "site:medium.com SEARCH_TERMS 2025 OR 2026", "maxPagesPerQuery": 1, "resultsPerPage": 10}` | For Medium scraping. Returns `organicResults` array. |

### DO NOT USE (broken actors)

| Actor | Why |
|-------|-----|
| `harvestapi~linkedin-post-search` | Returns 0 results |
| `trudax~reddit-scraper` | Requires paid rental |
| `cloud9_ai~medium-article-scraper` | Returns garbage |
| `ivanvs~medium-scraper` | Requires paid rental |

---

## 2. Known Issues Registry

Things we've hit before. Never re-discover these.

### KI-1: Notion has two MCP servers connected to different workspaces
- `mcp__notion_api__*` connects to the founder's Notion workspace (CRM) - CORRECT for reads
- `mcp__claude_ai_Notion__*` connects to a different workspace - WRONG for CRM data
- **Rule:** Use `mcp__notion_api__*` for all database queries. Use `mcp__claude_ai_Notion__notion-update-page` ONLY if the page is accessible (test first with a read). If 404, fall back to manual update instructions.

### KI-2: Notion API-patch-page only updates title
- `mcp__notion_api__API-patch-page` accepts only `title` in its properties schema
- Cannot update: Role, Company, Status, DP Status, Last Contact, What They Care About, Strategic Value, Follow-up Action, Pushback, Email, LinkedIn, Priority, or any other field
- **Workaround:** For full property updates, try `mcp__claude_ai_Notion__notion-update-page` first. If 404 (wrong workspace), output the exact values the founder should update manually in Notion.

### KI-3: Notion Actions DB property names
- The Actions DB (`0718ee69-d9d0-473d-8182-732d21c60491`) does NOT have a property called "Status" (the standard Notion status property)
- Known properties: Action (title), Priority, Due, Type, Energy, Time Est, Contact, Notes, Action ID, Created
- **Rule:** Do not filter by "Status" on Actions DB. Filter by Priority or Due instead.

### KI-4: Notion Investor Pipeline DB property names
- The Investor Pipeline DB (`fd92016f-7890-40c3-abe9-154c864e05b3`) does NOT have a property called "Status"
- Known properties: Fund (title), Stage, Thesis Fit, Next Date, Next Step, Key Quote, Pass Reason, Check Size, Contact, Investor Type, Deal ID, Updated
- **Rule:** Filter by "Stage" not "Status" on Pipeline DB.

### KI-5: Apify MCP tools may not load
- The Apify MCP server (`@apify/actors-mcp-server`) sometimes doesn't register its tools as deferred tools
- When this happens, `ToolSearch` for "apify" returns nothing
- **Rule:** Always test Apify MCP first via ToolSearch. If unavailable, immediately switch to **Chrome browser automation** fallback (navigate to LinkedIn/Reddit/X directly via `mcp__claude-in-chrome__*`). Do NOT use REST API curl. Do NOT waste tokens retrying MCP.

### KI-6: VC Pipeline API requires local server
- `http://localhost:5050/api/pipeline` only works if the Python app is running
- Location: configured in `my-project/founder-profile.md` or local project directory
- `WebFetch` returns "Invalid URL" for localhost URLs
- **Rule:** Use `curl` via Bash tool, not WebFetch. If server is down, ask founder to start it or proceed without warm intro matching.

### KI-7: Emdash ban
- NEVER use emdashes in any output. Use commas, periods, or hyphens instead.
- This applies to JSON data, copy blocks, and all written content.

---

## 3. Session Budget & Hard Splits

The morning routine is too large for one context window. Plan for splits.

### Session 1: Data Collection (Steps 0f through 5.9b)
- **Expected context usage:** 60-80%
- **Primary deliverable:** Structured data for all steps
- **Exit trigger:** Context > 70% OR Step 5.9b complete, whichever comes first
- **On exit:** Write `output/morning-handoff-YYYY-MM-DD.json` with all collected data, then tell founder to start Session 2

### Session 2: HTML Generation (Step 11)
- **Input:** Read `output/morning-handoff-YYYY-MM-DD.json`
- **Primary deliverable:** `output/schedule-data-YYYY-MM-DD.json` + built HTML
- **Expected context usage:** 10-20%
- **Detection:** If handoff file exists and is from today, skip all data collection steps

### Handoff File Format

```json
{
  "date": "2026-03-13",
  "session": 1,
  "steps_completed": ["0f", "1", "1.5", "2", "3", "3.5", "3.8", "4", "5.9", "5.9b"],
  "steps_skipped": [],
  "steps_failed": [],
  "calendar": { "events": [...] },
  "gmail": { "highlights": [...] },
  "notion": { "actions": [...], "pipeline": [...], "dp_contacts": [...] },
  "meeting_prep": [...],
  "signals": [...],
  "lead_sourcing": { "qualified": [...], "tier_a": [...] },
  "engagement_hitlist": [...],
  "content_drafts": { "linkedin": "...", "x": "...", "medium_topic": "..." },
  "pipeline_status": { "dp_prospects": 17, "outreach_sent": 3 },
  "fyi_notes": [...]
}
```

### Context-Saving Rules (from commands.md, repeated here for visibility)
- Never hold raw Apify results in context. Save to `output/lead-gen/` immediately.
- Never generate content for the wrong day (Tue=TL, Fri=Medium).
- Step 5.9 Phase 2: score in batches of 10. Discard sub-10 immediately.
- Step 5.9b: cap at 10 engagement targets.
- Meeting prep: only today's meetings get full prep.
- Steps 6-7: skip if context < 40%.

---

## 4. Step Completion Log

Every step writes to `output/morning-log-YYYY-MM-DD.json` as it completes. This is the flight recorder.

### Log Format

```json
{
  "date": "2026-03-13",
  "session_start": "2026-03-13T09:00:00-07:00",
  "steps": {
    "0f_connection_check": {
      "status": "done|failed|skipped",
      "timestamp": "2026-03-13T09:01:00-07:00",
      "result": "7/7 passed",
      "error": null
    },
    "0a_checkpoint": { "status": "done", "timestamp": "...", "result": "no prior changes" },
    "0b_missed_debrief": { "status": "done", "timestamp": "...", "result": "none found" },
    "0c_load_canonical": { "status": "done", "timestamp": "...", "result": "loaded" },
    "0d_load_voice": { "status": "done", "timestamp": "...", "result": "loaded" },
    "0e_load_audhd": { "status": "done", "timestamp": "...", "result": "loaded" },
    "1_calendar": { "status": "done", "timestamp": "...", "result": "5 events loaded" },
    "1_gmail": { "status": "done", "timestamp": "...", "result": "30 messages, 5 actionable" },
    "1_notion_actions": { "status": "done", "timestamp": "...", "result": "12 actions pulled" },
    "1_notion_pipeline": { "status": "done", "timestamp": "...", "result": "8 active deals" },
    "1_vc_pipeline": { "status": "skipped", "timestamp": "...", "result": null, "error": "localhost:5050 not running" },
    "1.5_warm_intro": { "status": "skipped", "timestamp": "...", "result": null, "error": "depends on VC pipeline" },
    "2_meeting_prep": { "status": "done", "timestamp": "...", "result": "1 meeting prepped (Sim)" },
    "2.5_x_activity": { "status": "done", "timestamp": "...", "result": "3 replies, 2 DM opps" },
    "3_linkedin_activity": { "status": "done", "timestamp": "...", "result": "2 re-engage, 1 new opp" },
    "3.2_publish_reconciliation": { "status": "done", "timestamp": "...", "result": "1 direct publish detected" },
    "3.5_dp_pipeline": { "status": "done", "timestamp": "...", "result": "17 prospect, 3 outreach, 0 active" },
    "3.7_content_intel": { "status": "skipped", "timestamp": "...", "result": null, "error": "Monday only" },
    "3.8_dm_check": { "status": "done", "timestamp": "...", "result": "2 DM replies, 1 accept" },
    "4_signals_linkedin": { "status": "done", "timestamp": "...", "result": "Signals LinkedIn post drafted" },
    "4_x_signals": { "status": "done", "timestamp": "...", "result": "X signals post drafted" },
    "4_x_hot_take": { "status": "done", "timestamp": "...", "result": "X hot take drafted" },
    "4_x_bts": { "status": "done", "timestamp": "...", "result": "X BTS post drafted" },
    "4_medium_draft": { "status": "done", "timestamp": "...", "result": "Medium draft written (Mon only)" },
    "4_tl_linkedin": { "status": "done", "timestamp": "...", "result": "TL LinkedIn post drafted (Tue/Thu)" },
    "4_tl_x": { "status": "done", "timestamp": "...", "result": "TL X post drafted (Tue/Thu)" },
    "4.1_value_drops": { "status": "done", "timestamp": "...", "result": "1 value drop generated" },
    "4.5_marketing_health": { "status": "done", "timestamp": "...", "result": "assets current" },
    "5_site_metrics": { "status": "skipped", "timestamp": "...", "result": null, "error": "Monday only" },
    "5.5_prospect_tracking": { "status": "skipped", "timestamp": "...", "result": null, "error": "Monday only" },
    "5.8_temperature_scoring": { "status": "done", "timestamp": "...", "result": "3 hot, 5 warm, 9 cool" },
    "5.85_pipeline_followup": { "status": "done", "timestamp": "...", "result": "5 overdue, 3 follow-ups generated" },
    "5.9_lead_sourcing": { "status": "done", "timestamp": "...", "result": "4 queries, 2 qualified" },
    "5.9b_engagement_hitlist": { "status": "done", "timestamp": "...", "result": "8 items across 4 types" },
    "6_decision_compliance": { "status": "done", "timestamp": "...", "result": "all clear" },
    "7_positioning_freshness": { "status": "done", "timestamp": "...", "result": "all current" },
    "8_briefing_output": { "status": "done", "timestamp": "...", "result": "briefing printed" },
    "8.5_start_here": { "status": "done", "timestamp": "...", "result": "Reply to Phil Venables" },
    "9_notion_push": { "status": "done", "timestamp": "...", "result": "5 actions created" },
    "10_daily_checklists": { "status": "done", "timestamp": "...", "result": "pages updated" },
    "11_html_output": { "status": "done", "timestamp": "...", "result": "daily-schedule-2026-03-13.html opened" }
  },
  "audit": null
}
```

### How to Write the Log

All logging uses MCP tools. No shell scripts required:

```
# Create the log at session start:
Use the `log_init` MCP tool with date parameter

# Log a step (done/failed/skipped/partial):
Use the `log_step` MCP tool with date, step_id, status, result, and error parameters

# Add an action card (for any founder-facing draft):
Use the `log_add_card` MCP tool with date, card_id, card_type, target, text, and url parameters

# Gate check (before Steps 8, 9, 11):
Use the `log_gate_check` MCP tool with date, gate_name, passed, and missing parameters

# State checksums:
Use the `log_checksum` MCP tool with date, phase (start/end), field_name, and value parameters

# Mark cards as delivered (after HTML opens):
Use the `log_deliver_cards` MCP tool with date parameter

# Verification queue:
Use the `log_verify` MCP tool with date, claim, source_file, verified, and result parameters
```

Every tool call writes directly to disk. Context rot cannot affect it.

---

## 5. Execution Gates

Certain steps MUST NOT start until all prior steps are done or explicitly skipped. This prevents rushing to output without doing the work.

### Gate Definitions

| Gate Step | Cannot Start Until | Why |
|-----------|-------------------|-----|
| **Step 8 (briefing output)** | Steps 1 through 5.9b all logged as done/skipped | Briefing must reflect ALL collected data, not partial |
| **Step 9 (Notion push)** | Steps 1-8 done/skipped | Can't push actions that weren't generated |
| **Step 11 (HTML output)** | Steps 1-10 all done/skipped | HTML is the final deliverable, must include everything |

### Deliverables Checklist (ENFORCED at Step 8 gate)

Before Step 8 can proceed, Claude MUST verify these deliverables exist in today's action cards or output files. Not "step logged" but "output produced."

**Day-invariant (every day):**
- [ ] At least 3 pipeline follow-up items (Step 5.85) with copy-paste text. This means: Notion Contacts DB queried for warm/active contacts with Last Contact > 7 days, follow-up DMs/emails drafted for each, added to HTML. Checking who replied to YESTERDAY's messages is NOT the same as following up with the existing pipeline.
- [ ] LinkedIn engagement comments with copy-paste text (Step 5.9b)
- [ ] Connection requests with copy-paste notes (Step 5.9b)
- [ ] LinkedIn Comments tab was checked (Step 3) - log must say "comments tab" not just "posts"

**Mon/Wed/Fri:**
- [ ] Signals LinkedIn post with copy-paste text (Step 4)
- [ ] X signals post, 280 char max (Step 4)
- [ ] X hot take (Step 4)
- [ ] X BTS post (Step 4)

**Monday additional:**
- [ ] Medium draft, 800+ words (Step 4)
- [ ] Content intelligence baselines updated (Step 3.7)

**Tue/Thu:**
- [ ] TL LinkedIn post with copy-paste text (Step 4)
- [ ] TL X post (Step 4)

**Loop checks (every day):**
- [ ] Step 0b.5 ran (loop escalation)
- [ ] Step 5.86 ran (loop review with follow-ups generated)
- [ ] No level 3 loops remain unresolved (`kipi://loops/open` MCP resource (filter for min_level=3) returns empty)
- [ ] Every action card generated today has a corresponding loop opened in `output/open-loops.json`

**If any deliverable is missing:** Do NOT proceed to Step 8. Go back and generate it. The HTML is useless without copy-paste content.

**Step 4.1 value drops:** REQUIRED (moved from optional). If today's signals match any active prospect by industry/role/tools, a personalized value-drop message MUST be generated. If no signals match any prospect, log "no matches" with the reason.

**Step 3 LinkedIn Comments tab:** The step result must explicitly mention "comments tab checked" or it fails the deliverables check. Checking only the Posts tab is incomplete.

---

### Echo of Prompt (REQUIRED before every step)

Before executing ANY step, Claude MUST run the step loader to re-inject that step's requirements into context:
```
Use the `kipi_load_step` MCP tool with the step number
```
This combats "Lost in the Middle" - the research-proven phenomenon where LLMs forget instructions from earlier in the conversation. The step loader extracts the specific step definition from commands.md and prints it fresh. Claude MUST read this output before executing the step. This is NOT optional. Skipping the step loader is equivalent to skipping the step itself.

### HTML Build Verification (AUTOMATIC)

The `kipi_build_schedule` MCP tool automatically runs `verify-schedule.py` before generating HTML. If verification fails, the HTML is NOT built. Claude cannot bypass this. The verification checks:
- Pipeline follow-ups section exists with 3+ items with copy-paste text
- Day-specific content exists (signals Mon/Wed/Fri, TL Tue/Thu, Medium Mon, Kipi Wed)
- Section ordering is correct (follow-ups before new leads)
- Items have energy tags

If the build is blocked, Claude must go back and complete the missing work, then rebuild.

### How Gates Work

Before starting any gate step, Claude MUST:
1. Re-read the morning log file from disk (not from context memory)
2. Verify the Deliverables Checklist above (Step 8 gate only)
3. Check that every step before the gate is logged as `done` or `skipped`
4. If any prior step shows no entry (never logged), STOP and report:

```
GATE CHECK FAILED at Step [gate step]

Step [missing step] was never logged. It was either skipped silently or forgotten.
Cannot proceed to [gate step] without completing or explicitly skipping [missing step].

Options:
1. Go back and run the missing step
2. Log it as skipped with a reason: [founder tells me why]
```

A step can only be marked `skipped` if:
- It's day-conditional and today isn't the right day (e.g., Monday-only steps on a Friday)
- A dependency failed (e.g., VC Pipeline API down) - BUT Claude must notify the founder and wait for the founder to decide next steps. Claude does not self-decide the fallback.
- The founder explicitly says "skip it"

**Claude cannot self-authorize skipping a required step. EVER.** This means:
- Claude cannot decide "this is lower priority today" and skip a step
- Claude cannot decide "we did this yesterday so we don't need it today" and skip a step
- Claude cannot decide "context is running low" and skip a step
- If Claude thinks a step should be skipped, it MUST ask the founder first: "Step X is next. Do you want me to run it or skip it today?"
- If the founder doesn't respond, the step runs. The default is ALWAYS run, never skip.
- Skipping without asking is a rule violation that gets flagged in the audit.

---

## 6. Action Cards with Confirmation Tracking

Action cards track the difference between "Q drafted something" and "the founder actually did it." This prevents false assumptions about what happened.

### Action Card Format (in morning log)

```json
{
  "action_cards": [
    {
      "id": "C1",
      "type": "linkedin_comment",
      "target": "Michael Morrison",
      "draft_text": "That governance gap in IAM is exactly...",
      "card_delivered": true,
      "founder_confirmed": false,
      "logged_to": []
    },
    {
      "id": "P1",
      "type": "linkedin_publish",
      "target": "Signals post - CISA advisories",
      "draft_text": "Three critical security issues...",
      "card_delivered": true,
      "founder_confirmed": false,
      "logged_to": []
    },
    {
      "id": "E1",
      "type": "email",
      "target": "James Wilson (JPMorgan)",
      "draft_text": "Hey James, happy Friday...",
      "card_delivered": true,
      "founder_confirmed": false,
      "logged_to": []
    }
  ]
}
```

### Rules

- **"card_delivered" = true** means Q showed it to the founder in the HTML or briefing. This is NOT "done."
- **"founder_confirmed" = true** means the founder explicitly said they did it (in a future message or session). Only THEN does Q update state files.
- **"logged_to"** lists which state files were updated when the action was confirmed. Must include ALL relevant files (LinkedIn Tracker, Contacts DB, morning-state, etc.).
- Cards stay in `delivered, unconfirmed` state between sessions.
- **Next morning, Step 0b reads the previous day's morning log** and asks about each unconfirmed card: "Yesterday I drafted these for you. Which ones did you actually do?"
- Never log a comment/DM/email as "posted" or "sent" until the founder confirms it.
- Never update LinkedIn Tracker, Contacts DB, or relationship status based on a draft. Only on confirmation.

### How This Changes the Morning Routine

- Step 5.9b (engagement hitlist): Creates action cards for each comment/DM/request
- Step 4 (content): Creates action cards for each post draft
- Step 8 (briefing): Creates action cards for email replies
- Step 11 (HTML): All action cards appear as checkable items
- Step 0b (next morning): Reads yesterday's unconfirmed cards, asks founder

---

## 7. State File Checksums

At session start and end, read key fields from critical state files and check for consistency. This catches drift between files that should agree.

### Tracked State Files

| File | Key Fields to Snapshot |
|------|----------------------|
| `memory/morning-state.md` | Last sync dates (Calendar, Gmail, Notion, LinkedIn, X) |
| `my-project/relationships.md` | Count of active DP prospects, count of active VC conversations |
| `my-project/current-state.md` | Demo status, what's built vs vision |
| `canonical/decisions.md` | Rule count, last rule added |
| `memory/marketing-state.md` | Content cadence counts, publish log last entry |

### Checksum Format (in morning log)

```json
{
  "state_checksums": {
    "session_start": {
      "morning_state_last_calendar_sync": "2026-03-11",
      "morning_state_last_gmail_sync": "2026-03-11",
      "relationships_dp_prospect_count": 17,
      "relationships_active_vc_count": 5,
      "decisions_rule_count": 17,
      "marketing_state_last_publish": "2026-03-10"
    },
    "session_end": {
      "morning_state_last_calendar_sync": "2026-03-13",
      "morning_state_last_gmail_sync": "2026-03-13",
      "relationships_dp_prospect_count": 17,
      "relationships_active_vc_count": 5,
      "decisions_rule_count": 17,
      "marketing_state_last_publish": "2026-03-10"
    },
    "drift_detected": [
      "morning_state sync dates updated (2026-03-11 -> 2026-03-13)"
    ]
  }
}
```

### Rules

- At session START (Step 0c): Read key fields from all tracked files, log to morning log under `state_checksums.session_start`
- At session END (Step 12 audit): Re-read the same fields, log under `state_checksums.session_end`
- Compare start vs end. Any change should be explainable by what the session did.
- **Cross-file consistency check:** If `relationships.md` says 17 DP prospects but the Notion Contacts DB query returned 15 with DP status, flag the divergence.
- If files disagree, update them ALL to match reality (the Notion DB is the source of truth for counts).

---

## 8. Verification Queue

Claims that cross sessions get verified. Q does not trust data older than 48 hours without re-checking.

### What Gets Verified

| Claim Type | How to Verify | Staleness Threshold |
|------------|--------------|-------------------|
| "Commented on [person]'s post" | Check LinkedIn via Chrome (Comments tab) or Apify | 24h |
| "Sent DM to [person]" | Check LinkedIn messaging via Chrome | 24h |
| "[Person] accepted connection" | Check invitation-manager via Chrome | 48h |
| "Email sent to [person]" | Check Gmail sent folder | 48h |
| "Lead score [X]" | Re-check if original post is > 72h old | 72h |
| "DP Status = [X]" | Query Notion Contacts DB | 48h |
| "[Person] replied" | Check Gmail inbox or LinkedIn DMs | 24h |

### Verification Queue Format (in morning log)

```json
{
  "verification_queue": [
    {
      "claim": "Commented on Michael Morrison's IAM post",
      "source_file": "linkedin-tracker entry from 2026-03-12",
      "verified": false,
      "verification_method": "Check LinkedIn comments tab via Chrome",
      "result": null
    },
    {
      "claim": "Phil Venables reviewing materials",
      "source_file": "morning-state.md open items",
      "verified": true,
      "verification_method": "Gmail shows his reply + Assaf's response with attachments",
      "result": "Confirmed. Materials sent 2026-03-13."
    }
  ]
}
```

### Rules

- Step 0b (session start): Read previous day's morning log. Check for unverified claims. Add them to today's verification queue.
- Step 3.8 (DM/accept check): Naturally verifies DM and connection claims as part of the check.
- Any claim marked "done" in a state file that can't be verified gets flagged: "UNVERIFIED: [claim]. Re-checking needed."
- Never carry an unverified claim forward for more than 2 sessions. After 2 sessions without verification, downgrade it: mark as "unconfirmed" in the relevant state file.

---

## 9. Post-Execution Audit Harness

After Step 11 (or whenever the routine ends), run the audit. This MUST happen even if context is tight.

The audit script (`q-system/.q-system/audit-morning.py`) checks:
1. Step completion against expected steps for the day
2. Gate compliance (were gate checks actually performed?)
3. Action card counts (how many delivered, how many still unconfirmed from yesterday?)
4. State file drift (did checksums change as expected?)
5. Verification queue (any stale unverified claims?)

Run:
```bash
python3 q-system/.q-system/audit-morning.py q-system/output/morning-log-YYYY-MM-DD.json
```

Show the output to the founder. This is not optional. If the verdict is not COMPLETE, the founder sees exactly what was missed.

---

## 10. Integration Points

| System File | What Changes |
|-------------|-------------|
| `commands.md` Step 0f | References this file for tool manifest and known issues |
| `commands.md` Step 0b | Reads previous day's morning log for unconfirmed action cards |
| `commands.md` Step 0c | Snapshots state file checksums at session start |
| `commands.md` every step | Writes completion to morning log + creates action cards for founder-facing outputs |
| `commands.md` Steps 8, 9, 11 | Gate check: re-read morning log from disk, verify all prior steps logged |
| `commands.md` Step 12 | Run audit harness, snapshot state checksums, verify claims |
| `CLAUDE.md` | Rule: "Read `.q-system/preflight.md` before every `/q-morning` run" |
| `memory/morning-state.md` | Audit results appended to track completion rate over time |

### Reading Order for `/q-morning`

1. `.q-system/preflight.md` (this file) - tool manifest, known issues, session budget, gates, action cards
2. Read previous day's morning log (if exists) for unconfirmed action cards and stale verification items
3. Run Step 0f connection checks using the tool manifest
4. Create today's morning log file (empty structure with all sections)
5. Snapshot state file checksums (Step 0c)
6. `.q-system/commands.md` - execute steps, logging each to morning log
7. At gate steps (8, 9, 11): re-read morning log from disk, check all prior steps
8. After Step 11: run audit harness, show result to founder

### Complete Morning Log Format (with all new fields)

```json
{
  "date": "2026-03-13",
  "session_start": "2026-03-13T09:00:00-07:00",
  "steps": {
    "0f_connection_check": {"status": "done", "timestamp": "...", "result": "7/7 passed", "error": null}
  },
  "action_cards": [
    {
      "id": "C1",
      "type": "linkedin_comment",
      "target": "Michael Morrison",
      "draft_text": "That governance gap...",
      "card_delivered": true,
      "founder_confirmed": false,
      "logged_to": []
    }
  ],
  "state_checksums": {
    "session_start": {},
    "session_end": {},
    "drift_detected": []
  },
  "verification_queue": [
    {
      "claim": "...",
      "source_file": "...",
      "verified": false,
      "verification_method": "...",
      "result": null
    }
  ],
  "gates_checked": {
    "step_8": {"checked": true, "all_prior_done": true, "missing": []},
    "step_9": {"checked": true, "all_prior_done": true, "missing": []},
    "step_11": {"checked": true, "all_prior_done": true, "missing": []}
  },
  "audit": {
    "verdict": "COMPLETE",
    "completion_pct": 100,
    "action_cards_delivered": 8,
    "action_cards_confirmed_from_yesterday": 5,
    "state_drift_count": 1,
    "unverified_claims": 0
  }
}
```
