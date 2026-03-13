# Q Instance Commands

> These are conventions for interacting with the Q Founder OS. Use them as natural language triggers.

| Command | Purpose | Mode |
|---------|---------|------|
| `/q-begin` | Start a new session. Read all canonical files to load current state. | - |
| `/q-status` | Report current state from `my-project/progress.md`. | - |
| `/q-calibrate` | Update canonical files based on new information or feedback. | CALIBRATE |
| `/q-create [type] [audience]` | Generate a specific output (talk track, email, slide text, memo). | CREATE |
| `/q-debrief [person]` | Process a conversation using the debrief template. **Highest-priority.** | DEBRIEF |
| `/q-plan` | Review relationships, objections, proof gaps. Propose next actions. | PLAN |
| `/q-draft [type] [audience]` | Generate a one-off output to `output/drafts/`. | CREATE |
| `/q-checkpoint` | Save canonical state. Verify consistency. Log to progress.md. | - |
| `/q-end` | End session. Auto-checkpoints, then summarizes all changes. | - |
| `/q-sync-notion` | Sync local files with Notion CRM (if configured). | CALIBRATE |
| `/q-morning` | Full morning briefing. See workflow below. | - |
| `/q-engage` | Social engagement mode. Proactive hitlists + reactive comments. | CREATE |
| `/q-investor-update` | Draft investor update email. | CREATE |
| `/q-market-plan` | Weekly content planning. | CREATE |
| `/q-market-create [type]` | Generate marketing content (linkedin, x, medium, email, deck). | CREATE |
| `/q-market-review [file]` | Validate content against guardrails. PASS/FAIL. | - |
| `/q-market-publish [file]` | Mark content published. Update tracking. | - |
| `/q-market-status` | Content pipeline snapshot. | - |
| `/q-wrap` | Evening wrap. 10-min end-of-day system health check. | - |
| `/q-handoff` | Session handoff. Context note for next session. | - |
| `/q-reality-check` | Challenger mode. Stress-test positioning and claims. | - |

## Usage Notes

- **`/q-morning` is the only command you need to start a day.** It auto-checkpoints, catches missed debriefs, and loads canonical state.
- **Debriefs happen automatically.** Paste a conversation transcript and the system auto-runs `/q-debrief`.
- **Modes are not sequential.** Switch freely.

## Example Flows

### After a meeting:
1. `/q-debrief [person]` - process the conversation
2. `/q-calibrate` - update canonical files if positioning shifted
3. `/q-draft email [person]` - draft follow-up

### Preparing for a meeting:
1. `/q-begin` - load current state
2. `/q-create talk-track [audience]` - generate tailored talking points
3. `/q-draft talking-points [person]` - person-specific prep

### Social engagement:

**Proactive mode (`/q-engage`):**
1. Pull contacts for active prospects / investors / partners
2. For each target: pull their recent social posts (via Apify or browser)
3. Cross-reference engagement tracker (enforce 1 comment/person/week)
4. Generate copy-paste ready comments
5. Output hitlist with copy buttons and links
6. After founder posts, log to tracker

**Reactive mode (screenshot shared):**
1. Identify person, role, company from screenshot
2. Check CRM for history
3. Generate 1 best comment (system picks the best style based on pool and context - no decision paralysis. Founder can ask for alternatives.)
4. Log to tracker after founder picks one

### Relationship Progression Engine

The system fully manages prospect relationships. The founder only:
1. Copy-pastes engagement actions from the hitlist

Everything else is automated: action detection, logging, status updates, next-step generation, follow-up scheduling. The system auto-detects comments posted, DMs sent, connection requests sent, accepts, replies, and scheduled calls. The founder NEVER needs to report what happened.

**Relationship ladder:**
```
STAGE 1: WARM UP
  Actions: Comment on 2-3 of their posts over 1-2 weeks
  Advance trigger: 2-3 comments posted

STAGE 2: CONNECT
  Actions: Send connection request
  Advance trigger: Request accepted

STAGE 3: FIRST DM
  Actions: Send value-first DM (no pitch)
  Advance trigger: They reply
  Timeout: 10 days no reply = value-drop. 14 days = Cooling.

STAGE 4: CONVERSATION
  Actions: Continue DM conversation, aim toward a call
  Advance trigger: Call scheduled

STAGE 5: DEMO/CALL
  Actions: Run the call, then debrief
  Advance trigger: /q-debrief completed
```

## Morning Briefing (`/q-morning`)

**Step 0 - Session bootstrap:**
- 0a: Checkpoint previous session + clean stale working memory (>48h in `memory/working/`). Read `memory/last-handoff.md` for prior session context. **MISSED WRAP DETECTION (A2):** If `memory/last-handoff.md` is missing or older than 24h AND there were canonical file changes yesterday (check mtimes), a wrap was missed. Run a lightweight retroactive wrap: count yesterday's completed Actions, note unfinished items, log to progress.md with "[Auto-recovered from missed wrap]". No guilt. **MID-MORNING RESUME:** If the handoff note says "morning routine split", skip to Step 11 using the collected data from the handoff note.
- 0b: Missed debrief detection (check calendar for unlogged meetings)
- 0c: Load canonical state (`/q-begin`)
- 0d: Load voice skill
- 0e: Load executive function skill (if AUDHD mode enabled)
- 0f: Standalone mode check - test MCP server connectivity. If any are down, note which steps will be skipped, proceed with everything else. Never fail the whole routine because one server is unavailable.
- 0g: Monthly checks (1st of month only): Decision origin audit (flag if >60% rubber-stamped). Review `memory/monthly/` files. Prediction calibration from `memory/working/predictions.jsonl`. Outreach A/B analysis by style code.
- 0h: **Context budget strategy:** If context runs low after Step 5.9b, auto-run `/q-handoff` with collected data and tell the founder to start a new session. The new session resumes at Step 11.

**Context-saving rules (ENFORCED):**
- Save raw scraper results to files, not context. Read back only qualified results.
- Only generate the content type assigned to today (e.g., Mon/Wed/Fri = signals, Tue/Thu = thought leadership).
- Process lead sourcing results in batches of 10, discard low scores immediately.
- Cap engagement targets at 10 per day.
- Full meeting prep only for TODAY's meetings.
- Steps 6-7 (compliance checks) can be skipped if context is low. Step 11 is the deliverable.

**Step 1 - Parallel data pull:**
- Calendar: Pull events for the current week. **NEW EVENT DETECTION (B4):** Cross-ref attendee names against CRM contacts. If a calendar event exists with a known prospect AND no matching action/tracker entry: auto-detect as newly scheduled meeting. Auto-create Meeting Prep action. Founder NEVER needs to report "scheduled a call with [name]."
- Email: Search last 48 hours (inbox AND sent). Cross-ref against contacts. **EMAIL CONVERSATION DETECTION (C4):** Check sent folder for outbound emails to prospects. Cross-ref inbox for replies. Auto-detect email conversations. For sent emails with no reply after 7+ days: note for channel death tracking.
- CRM: Pull overdue/due-today actions, pipeline follow-ups. **STALE ACTION CLEANUP (D5):** Auto-move any Actions with Due > 7 days past to Priority: Someday. Surface count in briefing without guilt.
- Pipeline: Check investor/prospect pipeline status

**Step 1.5 - Warm intro matching:**
- Cross-reference new prospects against existing contacts for warm paths
- Warm intro always beats cold outreach

**Step 2 - Meeting prep:**
- For each meeting this week: pull attendee profiles, CRM history, research
- Generate talking points based on their interests + your positioning

**Step 3 - Social activity review:**
- Check own posts for engagement, flag re-engagement opportunities
- Check target contacts for new posts to engage with
- Cross-reference engagement tracker for follow-ups due

**Step 3.5 - Pipeline check:**
- Count prospects by status
- Auto-close dead loops (3 touches + no response + 14 days)
- Flag pipeline health

**Step 4 - Content generation:**
- Fetch relevant signals/news for your industry
- Generate social posts (platform-specific)
- Generate thought leadership content (on schedule days)

**Step 4.1 - Value-first signal routing:**
- Match today's signals to contacts by industry/role
- Generate personalized value-drop messages
- No pitch, pure intel sharing

**Step 5 - Analytics (weekly):**
- Site metrics
- Content performance
- Prospect engagement tracking

**Step 5.9 - Lead sourcing (daily):**
- Phase 1: Run scrapers across platforms. **AUTO-ROTATION (C1):** Read `memory/morning-state.md` field `last_sourcing_day` (1-6). Auto-increment to next day. Founder NEVER needs to remember which queries to run.
- Phase 2: Read and qualify every result (no keyword filter)
- Phase 3: Generate personalized outreach
- Phase 4: Create CRM entries

**Step 5.9b - Daily engagement hitlist:**
- Pull recent posts from pipeline prospects
- Generate copy-paste comments, DMs, connection requests
- Must include all engagement types with sections even if empty

**Steps 6-7 - Compliance checks:**
- Decision rule compliance
- Positioning freshness

**Step 8 - Output briefing**

The briefing includes:
- **START HERE:** Single highest-value, lowest-friction task
- **TODAY'S FOCUS (CT1):** Top 3-5 prioritized items across all sections. "If you only have 30 minutes, do these." Mix of Quick Wins + at most 1 Deep Focus. Replaces scanning 15+ sections.
- Calendar, meeting prep, actions due, pipeline, engagement hitlist, content, etc.
- **Prospect temperature** includes relationship stage inline: `[Name] (score: 9, ↑) [Stage: Conversation] [DP: Outreach Sent]` - no cross-referencing needed (C2)

**Step 9 - Push actions to CRM**

**Step 10 - Update daily checklists**

**Step 10.5 - Auto-sync CRM (A3):** Push all morning routine changes to CRM in one batch. Founder NEVER needs to manually sync after mornings.

**Step 11 - MANDATORY: Generate daily schedule JSON + build HTML + open in browser**

This is the primary deliverable. Never end without it. Claude NEVER writes raw HTML.

1. **Read the schema:** `q-system/marketing/templates/schedule-data-schema.md`
2. **Generate JSON:** Write `q-system/output/schedule-data-YYYY-MM-DD.json` conforming to the schema
3. **Build HTML:** `bash q-system/marketing/templates/build-schedule.sh q-system/output/schedule-data-YYYY-MM-DD.json q-system/output/daily-schedule-YYYY-MM-DD.html`
4. **Open in browser:** `open q-system/output/daily-schedule-YYYY-MM-DD.html`
5. **Telegram push (if configured):** Send top 3 actions after HTML generation

The template (`daily-schedule-template.html`) is LOCKED. All CSS/JS/rendering is permanent. Never edit it during morning routine. If a visual bug is found, fix the template in a separate session.

---

## Evening Wrap (`/q-wrap`)

10-minute end-of-day system health check. 5 steps:

1. **Effort log** (2 min): Count actions taken today from CRM. Track effort, not outcomes.
2. **Unfinished actions triage** (3 min): What carries over? What's stale? No guilt.
3. **Debrief check** (1 min): Any meetings without debriefs?
4. **Canonical drift check** (2 min): Any insights not yet in canonical files?
5. **Tomorrow preview** (2 min): Calendar + prep status.

After wrap (all automatic, founder does nothing): auto-checkpoint, promote `memory/working/` to `memory/weekly/` if relevant, clean stale working memory. **Then auto-run `/q-handoff`** (the founder NEVER needs to run /q-handoff separately after /q-wrap. Always chained automatically).

---

## Session Handoff (`/q-handoff`)

Generates a context note for the next session at `memory/last-handoff.md`.

**Structure:** What happened this session, in-progress work, decisions made, files modified, blocked items, suggested next action.

**Triggers:** User says "done"/"wrapping up", context running low, after `/q-wrap`.

---

## Reality Check (`/q-reality-check`)

Challenger mode. Temporarily argues AGAINST current positioning.

1. Read all canonical files
2. Challenge positioning, traction, and market claims
3. Rate each claim: STRONG (data-backed), MODERATE (anecdotal), WEAK (assumption)
4. For WEAK claims: suggest a specific validation experiment
5. Output the hardest question a VC/buyer will ask that you can't answer yet

Run monthly or before major meetings. Not hostile, Socratic.

---

## Prediction Tracking

When generating outreach, log predictions to `memory/working/predictions.jsonl`:
```jsonl
{"date":"YYYY-MM-DD","prospect":"Name","channel":"linkedin_dm","prediction":"will_reply","confidence":0.7,"style":"V1","outcome":null,"outcome_date":null}
```

**Style codes for A/B testing:**
- V1: Value drop (signal share)
- Q1: Genuine question
- P1: Peer observation
- C1: Content reference
- W1: Warm intro follow-up

Monthly: calculate reply rate per style, shift toward best performers.

---

## Predict-First Prompting (Debriefs)

Before the founder describes a conversation, the system predicts:
- Top 3 likely objections surfaced
- Top 3 likely topics discussed
- Predicted relationship outcome (warmer/cooler/same)

After the founder describes it, compare. Wrong predictions reveal gaps in canonical files. Log accuracy to predictions.jsonl.

---

## Memory Management

**Time-stratified architecture:**
```
memory/
├── working/          # Session-scoped, ephemeral (<48h)
├── weekly/           # 7-day rolling window
├── monthly/          # Persistent insights
├── last-handoff.md   # Session handoff note
├── graph.jsonl       # Entity-relationship knowledge graph
└── morning-state.md  # Morning routine state tracker
```

**Lifecycle:**
- `working/` -> cleaned during `/q-morning` Step 0a or promoted during `/q-wrap`
- `weekly/` -> reviewed Monday mornings, promoted to monthly/ or archived
- `monthly/` -> reviewed 1st of month, promoted to canonical if proven

---

## Graph Knowledge Base

Structured triples in `memory/graph.jsonl`:
```jsonl
{"s":"Person Name","p":"works_at","o":"Company","t":"2026-03-12"}
{"s":"Person Name","p":"cares_about","o":"topic","t":"2026-03-12"}
{"s":"Connector","p":"introduced","o":"Person Name","t":"2026-03-12"}
```

Written during debriefs and lead sourcing. Queried via grep for meeting prep and warm intro matching.

---

## Decision Origin Tagging

All decisions in `canonical/decisions.md` must include origin tags:
- `[USER-DIRECTED]`, `[CLAUDE-RECOMMENDED -> APPROVED/MODIFIED/REJECTED]`, `[SYSTEM-INFERRED]`

Monthly audit (1st of month): flag if >60% are rubber-stamped approvals.

---

## Inter-Skill Review Gates

Before outputting factual claims about the founder's product:
1. Check canonical files (current-state.md, talk-tracks.md)
2. If not found: mark `{{UNVALIDATED}}`
3. If contradicts canonical: BLOCK output
