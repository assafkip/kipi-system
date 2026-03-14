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
| **Notion API** | Query your Contacts DB with `page_size: 1` | Returns `results` array | Some MCP servers have limited write support. Test writes before relying on them. | For reads: primary MCP. For writes: test first, fall back to manual instructions. |
| **Chrome** | `mcp__claude-in-chrome__tabs_context_mcp` | Returns tab list | Alerts/dialogs block all further commands. | None. Halt. |

### Non-Critical (proceed without, note in briefing)

| Tool | Test Command | Pass Criteria | Known Limitations | Fallback |
|------|-------------|---------------|-------------------|----------|
| **Apify** | Check if any `mcp__apify__*` tool is available via ToolSearch | MCP: tool schema returned | MCP tools sometimes don't load. REST API always works if you have a token. | REST API fallback via curl. |
| **NotebookLM** | `mcp__notebooklm__list_notebooks` | Returns notebook list | Session-based, may need re-auth. | Skip deep research in Step 2. Use Apify for profile data instead. |
| **Local pipeline API** | `curl -s http://localhost:PORT/api/endpoint` via Bash | Returns JSON | Must be running locally. | Skip warm intro matching. Note in briefing. |

### Confirmed Working Scrapers

> Fill this in as you validate actors for your use case.

| Actor/Tool | Input Format | Notes |
|-----------|-------------|-------|
| {{SCRAPER_1}} | {{INPUT_FORMAT}} | {{NOTES}} |
| {{SCRAPER_2}} | {{INPUT_FORMAT}} | {{NOTES}} |

### DO NOT USE (broken tools/actors)

| Tool | Why |
|------|-----|
| {{BROKEN_TOOL_1}} | {{REASON}} |

---

## 2. Known Issues Registry

Things you've hit before. Never re-discover these.

### KI-1: {{KNOWN_ISSUE_TITLE}}
- {{Description of the issue}}
- **Rule:** {{How to handle it}}

> Add entries here as you encounter issues. This prevents wasting time re-discovering the same bugs.

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
  "date": "YYYY-MM-DD",
  "session": 1,
  "steps_completed": [],
  "steps_skipped": [],
  "steps_failed": [],
  "calendar": { "events": [] },
  "gmail": { "highlights": [] },
  "crm": { "actions": [], "pipeline": [], "contacts": [] },
  "meeting_prep": [],
  "signals": [],
  "lead_sourcing": { "qualified": [], "tier_a": [] },
  "engagement_hitlist": [],
  "content_drafts": { "linkedin": "", "x": "", "medium_topic": "" },
  "pipeline_status": {},
  "fyi_notes": []
}
```

### Context-Saving Rules (from commands.md, repeated here for visibility)
- Never hold raw scraper results in context. Save to `output/lead-gen/` immediately.
- Never generate content for the wrong day (check the cadence schedule).
- Step 5.9 Phase 2: score in batches of 10. Discard sub-10 immediately.
- Step 5.9b: cap at 10 engagement targets.
- Meeting prep: only today's meetings get full prep.
- Steps 6-7: skip if context < 40%.

---

## 4. Step Completion Log

Every step writes to `output/morning-log-YYYY-MM-DD.json` as it completes. This is the flight recorder.

### How to Write the Log

All logging uses the helper script `.q-system/log-step.sh`. One-liners, no python required:

```bash
# Create the log at session start:
bash q-system/.q-system/log-step.sh DATE init

# Log a step (done/failed/skipped/partial):
bash q-system/.q-system/log-step.sh DATE step_id done "result summary"
bash q-system/.q-system/log-step.sh DATE step_id failed "" "error message"
bash q-system/.q-system/log-step.sh DATE step_id skipped "" "reason"

# Add an action card (for any founder-facing draft):
bash q-system/.q-system/log-step.sh DATE add-card C1 linkedin_comment "Person" "Text..." "https://url"

# Gate check (before Steps 8, 9, 11):
bash q-system/.q-system/log-step.sh DATE gate-check step_8 true ""
bash q-system/.q-system/log-step.sh DATE gate-check step_11 false "missing_step1,missing_step2"

# State checksums:
bash q-system/.q-system/log-step.sh DATE checksum-start field_name value
bash q-system/.q-system/log-step.sh DATE checksum-end field_name value

# Mark cards as delivered (after HTML opens):
bash q-system/.q-system/log-step.sh DATE deliver-cards

# Verification queue:
bash q-system/.q-system/log-step.sh DATE verify "claim text" "source file" true "confirmed"
```

Every command writes directly to disk. Context rot cannot affect it.

---

## 5. Execution Gates

Certain steps MUST NOT start until all prior steps are done or explicitly skipped.

| Gate Step | Cannot Start Until | Why |
|-----------|-------------------|-----|
| **Step 8 (briefing output)** | Steps 1 through 5.9b all logged as done/skipped | Briefing must reflect ALL collected data, not partial |
| **Step 9 (CRM push)** | Steps 1-8 done/skipped | Can't push actions that weren't generated |
| **Step 11 (HTML output)** | Steps 1-10 all done/skipped | HTML is the final deliverable, must include everything |

### How Gates Work

Before starting any gate step, Claude MUST:
1. Re-read the morning log file from disk (not from context memory)
2. Check that every step before the gate is logged as `done` or `skipped`
3. If any prior step shows no entry (never logged), STOP and report

A step can only be marked `skipped` if:
- It's day-conditional and today isn't the right day
- A dependency failed
- The founder explicitly says "skip it"

Claude cannot self-authorize skipping a required step.

---

## 6. Action Cards with Confirmation Tracking

Action cards track the difference between "Q drafted something" and "the founder actually did it."

### Rules

- **"card_delivered" = true** means Q showed it to the founder in the HTML or briefing. This is NOT "done."
- **"founder_confirmed" = true** means the founder explicitly said they did it. Only THEN does Q update state files.
- Cards stay in `delivered, unconfirmed` state between sessions.
- Next morning, Step 0b reads the previous day's morning log and asks about each unconfirmed card.
- Never log a comment/DM/email as "posted" or "sent" until the founder confirms it.
- Never update engagement tracker or relationship status based on a draft. Only on confirmation.

---

## 7. State File Checksums

At session start and end, read key fields from critical state files and check for consistency.

### Tracked State Files

| File | Key Fields to Snapshot |
|------|----------------------|
| `memory/morning-state.md` | Last sync dates |
| `my-project/relationships.md` | Count of active prospects, active conversations |
| `my-project/current-state.md` | Demo status, what's built vs vision |
| `canonical/decisions.md` | Rule count, last rule added |
| `memory/marketing-state.md` | Content cadence counts, publish log last entry |

---

## 8. Verification Queue

Claims that cross sessions get verified. Q does not trust data older than 48 hours without re-checking.

| Claim Type | How to Verify | Staleness Threshold |
|------------|--------------|-------------------|
| "Commented on [person]'s post" | Check social platform | 24h |
| "Sent DM to [person]" | Check messaging | 24h |
| "[Person] accepted connection" | Check invitation manager | 48h |
| "Email sent to [person]" | Check sent folder | 48h |
| "Lead score [X]" | Re-check if original post is > 72h old | 72h |

---

## 9. Post-Execution Audit Harness

After Step 11, run the audit. This MUST happen even if context is tight.

```bash
python3 q-system/.q-system/audit-morning.py q-system/output/morning-log-YYYY-MM-DD.json
```

Show the output to the founder. This is not optional.

---

## 10. Reading Order for `/q-morning`

1. `.q-system/preflight.md` (this file)
2. Read previous day's morning log (if exists) for unconfirmed action cards
3. Run Step 0f connection checks using the tool manifest
4. Create today's morning log file
5. Snapshot state file checksums (Step 0c)
6. `.q-system/commands.md` - execute steps, logging each to morning log
7. At gate steps (8, 9, 11): re-read morning log from disk, check all prior steps
8. After Step 11: run audit harness, show result to founder
