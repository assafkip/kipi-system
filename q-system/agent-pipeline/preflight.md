# Morning Routine Preflight & Execution Harness

> This file is the single source of truth for known issues, session management, gates, and audit rules. Read this BEFORE the step-orchestrator on every `/q-morning` run.

---

## 1. Tool Manifest

### Deterministic Python (handled by `kipi_morning_init` + `kipi_harvest`)

These are no longer checked by agents — Python handles them automatically:
- **File existence** — `kipi_preflight` checks canonical files, relationships, handoff
- **Data harvest** — `kipi_harvest` runs HTTP/Apify/local sources in Python, generates Chrome/MCP agent prompts
- **Apify** — managed by the harvest layer's `apify_executor.py` with budget enforcement
- **GA4, Notion (reads), VC Pipeline, Medium, Substack, Reddit** — all managed by harvest

### MCP Tools (checked at Phase 0 by the orchestrator)

| Tool | Quick Test | Fallback |
|------|-----------|----------|
| **Google Calendar** | `gcal_list_events` | Halt |
| **Gmail** | `gmail_search_messages` | Halt |
| **Chrome** | `tabs_context_mcp` | Halt (needed for LinkedIn harvest) |
| **Notion (writes)** | Tested during Phase 8 Notion push | Skip push, note in briefing |

### Harvest Source Configuration

Data sources are configured as YAML files in `kipi-mcp/sources/`. To add a new source, create a YAML file -- no code changes needed. See `source_registry.py` for the schema.

### Confirmed Working Apify Actors (used by harvest layer)

| Actor | Used For | Notes |
|-------|---------|-------|
| `apidojo/tweet-scraper` | X/Twitter posts (own + lead search) | Profile mode and search mode |
| `supreme_coder~linkedin-post` | LinkedIn lead search (via harvest) | Field is `urls` NOT `searchUrl` |
| `trudax~reddit-scraper-lite` | Reddit lead search (via harvest) | `restrict_sr=on` REQUIRED |
| `apify~google-search-scraper` | Medium search (via harvest) | Returns `organicResults` array |

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

### KI-5: Apify is now Python-managed (not MCP)
- Apify calls are handled by the harvest layer's `apify_executor.py`, not by an MCP server
- The `kipi_harvest` MCP tool runs Apify actors directly via the `apify-client` Python library
- Budget enforcement is built in -- see `apify_budget` table in SQLite
- If Apify fails (actor broken, budget exceeded), the harvest layer returns an error in the results. The Chrome harvest agent covers LinkedIn data independently.
- **Rule:** Do NOT try to call Apify MCP tools or use curl. Let `kipi_harvest` handle it.

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

The morning routine may exceed one context window. Plan for splits.

### Session 1: Init + Harvest + Analysis + Pipeline (Phases 0-4)
- **Expected context usage:** 60-80%
- **Primary deliverable:** All bus/ analysis files + harvest data in SQLite
- **Exit trigger:** Context > 70% OR Phase 4 complete, whichever comes first
- **On exit:** Write `output/morning-handoff-YYYY-MM-DD.json` with phase completion status, then tell founder to start Session 2

### Session 2: Compliance + Synthesis + Build (Phases 5-8)
- **Input:** Read `output/morning-handoff-YYYY-MM-DD.json`
- **Primary deliverable:** `output/schedule-data-YYYY-MM-DD.json` + built HTML
- **Expected context usage:** 20-40%
- **Detection:** If handoff file exists and is from today, skip Phases 0-4

### Handoff File Format

```json
{
  "date": "2026-04-01",
  "session": 1,
  "phases_completed": ["0", "0.6", "1", "2", "3", "4"],
  "phases_skipped": [],
  "phases_failed": [],
  "harvest_run_id": "2026-04-01-001",
  "bus_files_written": ["copy-diffs.json", "graph-digest.json", "signals.json", "hitlist.json"],
  "fyi_notes": []
}
```

Note: Most data is in SQLite (harvest) and bus/ files. The handoff only needs phase status and the harvest run_id so Session 2 can pick up where Session 1 left off.

### Context-Saving Rules
- Never hold raw harvest results in context. They're in SQLite -- use `kipi_get_harvest` to retrieve.
- Never generate content for the wrong day (Tue=TL, Fri=Medium).
- Lead scoring (Phase 4): score in batches of 10. Discard sub-10 immediately.
- Engagement hitlist (Phase 4): cap at 10 engagement targets.
- Meeting prep: only today's meetings get full prep.
- Phases 5-6: skip if context < 40%.

---

## 4. Step Completion Log

Every step writes to `{state_dir}/output/morning-log-YYYY-MM-DD.json` as it completes. This is the flight recorder.

### Log Format

```json
{
  "date": "2026-04-01",
  "session_start": "2026-04-01T09:00:00-07:00",
  "steps": {
    "phase_0_init": { "status": "done", "timestamp": "...", "result": "preflight ok, 3 stalls, energy=3" },
    "phase_0.6_monthly": { "status": "skipped", "timestamp": "...", "result": null, "error": "not 1st of month" },
    "phase_1_harvest": { "status": "done", "timestamp": "...", "result": "22 sources, 187 records" },
    "phase_2_analysis": { "status": "done", "timestamp": "...", "result": "7 agents, copy-diff + graph + x-activity + outbound + publish-recon + meeting-prep + warm-intro" },
    "phase_3_content": { "status": "done", "timestamp": "...", "result": "signals + value-routing + visuals + marketing-health" },
    "phase_4_pipeline": { "status": "done", "timestamp": "...", "result": "temp-scoring + leads + followup + loops + prospect-pipeline + connection-mining + hitlist" },
    "phase_5_compliance": { "status": "done", "timestamp": "...", "result": "compliance ok, positioning current, 0 overdue deliverables" },
    "phase_6_synthesis": { "status": "done", "timestamp": "...", "result": "schedule JSON + outreach queue" },
    "phase_7_build": { "status": "done", "timestamp": "...", "result": "HTML built, audit COMPLETE" },
    "phase_8_notion": { "status": "done", "timestamp": "...", "result": "5 actions pushed, checklists updated" }
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

# Gate check (before Phases 6, 7, 8):
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

| Gate Phase | Cannot Start Until | Why |
|-----------|-------------------|-----|
| **Phase 6 (synthesis)** | Phases 0-5 all logged as done/skipped | Synthesis must reflect ALL collected data, not partial |
| **Phase 7 (build + verify)** | Phase 6 done | HTML requires schedule JSON from synthesis |
| **Phase 8 (Notion push)** | Phase 7 done | Can't push actions that weren't generated |

### Deliverables Checklist (ENFORCED at Phase 6 gate)

Before Phase 6 (synthesis) can proceed, Claude MUST verify these deliverables exist in today's action cards or bus files. Not "phase logged" but "output produced."

**Day-invariant (every day):**
- [ ] At least 3 pipeline follow-up items (Phase 4, pipeline-followup) with copy-paste text
- [ ] LinkedIn engagement comments with copy-paste text (Phase 4, engagement-hitlist)
- [ ] Connection requests with copy-paste notes (Phase 4, engagement-hitlist)
- [ ] Outbound detection ran (Phase 2, outbound-detection)

**Mon/Wed/Fri:**
- [ ] Signals LinkedIn post with copy-paste text (Phase 3, signals-content)
- [ ] X signals post, 280 char max (Phase 3, signals-content)
- [ ] X hot take (Phase 3, signals-content)
- [ ] X BTS post (Phase 3, signals-content)

**Monday additional:**
- [ ] Medium draft, 800+ words (Phase 3, signals-content)
- [ ] Content intelligence baselines updated (Phase 4, content-intel)

**Tue/Thu:**
- [ ] TL LinkedIn post with copy-paste text (Phase 3, signals-content)
- [ ] TL X post (Phase 3, signals-content)

**Loop checks (every day):**
- [ ] Loop escalation ran (Phase 0, via kipi_morning_init bootstrap)
- [ ] Loop review ran (Phase 4, loop-review)
- [ ] No level 3 loops remain unresolved (`kipi://loops/open` resource, filter min_level=3)

**If any deliverable is missing:** Do NOT proceed to Phase 6. Go back and generate it.

**Value drops (Phase 3):** REQUIRED. If signals match any active prospect, a personalized value-drop MUST be generated. If no matches, log "no matches" with reason.

---

### Echo of Prompt (REQUIRED before every step)

Before executing ANY step, Claude MUST read the agent prompt file from `agent-pipeline/agents/` to re-inject that step's requirements into context. This combats "Lost in the Middle" - the research-proven phenomenon where LLMs forget instructions from earlier in the conversation. Claude MUST read the agent file before executing the step. This is NOT optional.

### HTML Build Verification (AUTOMATIC)

The `kipi_build_schedule` MCP tool automatically runs schedule verification before generating HTML. If verification fails, the HTML is NOT built. Claude cannot bypass this. You can also run `kipi_verify_schedule` directly to check a schedule JSON file. The verification checks:
- Pipeline follow-ups section exists with 3+ items with copy-paste text
- Day-specific content exists (signals Mon/Wed/Fri, TL Tue/Thu, Medium Mon, Kipi Wed)
- Section ordering is correct (follow-ups before new leads)
- Items have energy tags

If the build is blocked, Claude must go back and complete the missing work, then rebuild.

### How Gates Work

Before starting any gate phase, Claude MUST:
1. Re-read the morning log file from disk (not from context memory)
2. Verify the Deliverables Checklist above (Phase 6 gate only)
3. Check that every phase before the gate is logged as `done` or `skipped`
4. If any prior phase shows no entry (never logged), STOP and report:

```
GATE CHECK FAILED at Phase [N]

Phase [missing] was never logged. It was either skipped silently or forgotten.
Cannot proceed to Phase [N] without completing or explicitly skipping Phase [missing].

Options:
1. Go back and run the missing phase
2. Log it as skipped with a reason: [founder tells me why]
```

A phase can only be marked `skipped` if:
- It's day-conditional and today isn't the right day (e.g., Monday-only agents on a Friday)
- A dependency failed -- BUT Claude must notify the founder and wait for the founder to decide next steps.
- The founder explicitly says "skip it"

**Claude cannot self-authorize skipping a required phase. EVER.** The default is ALWAYS run, never skip. Skipping without asking is a rule violation flagged in the audit.

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
- **Next morning, Phase 0 (via kipi_morning_init) reads the previous day's morning log** and recovers unconfirmed cards. The founder is shown: "Yesterday I drafted these for you. Which ones did you actually do?"
- Never log a comment/DM/email as "posted" or "sent" until the founder confirms it.
- Never update LinkedIn Tracker, Contacts DB, or relationship status based on a draft. Only on confirmation.

### How This Changes the Morning Routine

- Phase 4 (engagement hitlist): Creates action cards for each comment/DM/request
- Phase 3 (content): Creates action cards for each post draft
- Phase 6 (synthesis): Creates action cards for email replies
- Phase 7 (HTML build): All action cards appear as checkable items
- Phase 0 (next morning, via kipi_morning_init): Reads yesterday's unconfirmed cards

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

- At session START (Phase 0, via kipi_morning_init): Key fields checksummed automatically, returned in bootstrap result
- At session END (Phase 7, audit): Re-read the same fields, log under `state_checksums.session_end`
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

- Phase 0 (session bootstrap): Reads previous day's morning log. Checks for unverified claims. Adds them to today's verification queue.
- Phase 2 (outbound-detection): Naturally verifies DM and connection claims as part of the check.
- Any claim marked "done" in a state file that can't be verified gets flagged: "UNVERIFIED: [claim]. Re-checking needed."
- Never carry an unverified claim forward for more than 2 sessions. After 2 sessions without verification, downgrade to "unconfirmed".

---

## 9. Post-Execution Audit Harness

After Phase 7 (or whenever the routine ends), run the audit. This MUST happen even if context is tight.

The `kipi_audit_morning` MCP tool checks:
1. Phase completion against expected phases for the day
2. Gate compliance (were gate checks actually performed?)
3. Action card counts (how many delivered, how many still unconfirmed from yesterday?)
4. State file drift (did checksums change as expected?)
5. Verification queue (any stale unverified claims?)

Run: Use the `kipi_audit_morning` MCP tool with log_file="{state_dir}/output/morning-log-YYYY-MM-DD.json"

Show the output to the founder. This is not optional. If the verdict is not COMPLETE, the founder sees exactly what was missed.

---

## 10. Integration Points

| System File | What Changes |
|-------------|-------------|
| `kipi_morning_init` | Replaces preflight + bootstrap + canonical digest agents with Python |
| `kipi_harvest` | Replaces all data-pull agents with Python + generated prompts |
| All analysis agents | Read from `kipi_get_harvest` instead of bus/ files |
| Step-orchestrator gates | Gate check: re-read morning log from disk, verify all prior phases logged |
| Audit harness | Run audit, verify claims |
| `preflight-audit.md` rule | "Read `preflight.md` before every `/q-morning` run" |

### Reading Order for `/q-morning`

1. `preflight.md` (this file) -- known issues, session budget, gates, action cards
2. Call `kipi_morning_init` -- handles preflight, bootstrap, canonical digest, bus setup
3. Quick MCP checks (Calendar, Gmail)
4. Call `kipi_harvest` -- runs Python sources, returns agent prompts
5. `step-orchestrator.md` -- execute Phases 1-8, logging each to morning log
6. At gate phases (6, 7, 8): re-read morning log from disk, check all prior phases
7. After Phase 7: run audit harness, show result to founder

### Complete Morning Log Format (with all fields)

```json
{
  "date": "2026-04-01",
  "session_start": "2026-04-01T09:00:00-07:00",
  "steps": {
    "phase_0_init": {"status": "done", "timestamp": "...", "result": "preflight ok, energy=3", "error": null},
    "phase_1_harvest": {"status": "done", "timestamp": "...", "result": "22 sources, 187 records"},
    "phase_2_analysis": {"status": "done", "timestamp": "...", "result": "7 agents completed"},
    "phase_3_content": {"status": "done", "timestamp": "...", "result": "signals + value-routing + visuals"},
    "phase_4_pipeline": {"status": "done", "timestamp": "...", "result": "scoring + leads + hitlist"},
    "phase_5_compliance": {"status": "done", "timestamp": "...", "result": "all clear"},
    "phase_6_synthesis": {"status": "done", "timestamp": "...", "result": "schedule JSON built"},
    "phase_7_build": {"status": "done", "timestamp": "...", "result": "HTML built, audit COMPLETE"},
    "phase_8_notion": {"status": "done", "timestamp": "...", "result": "5 actions pushed"}
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
    "phase_6": {"checked": true, "all_prior_done": true, "missing": []},
    "phase_7": {"checked": true, "all_prior_done": true, "missing": []},
    "phase_8": {"checked": true, "all_prior_done": true, "missing": []}
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
