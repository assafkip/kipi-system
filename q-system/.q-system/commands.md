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
| `/q-content-intel` | Content intelligence. Scrape own content, analyze what works, update content-intelligence.md. | CALIBRATE |
| `/q-investor-update` | Draft milestone-triggered investor update email. | CREATE |
| `/q-market-plan` | Weekly content planning. | CREATE |
| `/q-market-create [type] [topic]` | Generate marketing content (linkedin, x, medium, one-pager, outreach, deck, follow-up, substack). | CREATE |
| `/q-market-review [file]` | Validate content against guardrails. PASS/FAIL. | - |
| `/q-market-publish [file]` | Mark content published. Update tracking. | - |
| `/q-market-assets` | Refresh reusable assets from canonical files. Flag stale items. | CALIBRATE |
| `/q-market-status` | Content pipeline snapshot. | - |
| `/q-wrap` | Evening wrap. 10-min end-of-day system health check. | - |
| `/q-handoff` | Session handoff. Context note for next session. | - |
| `/q-reality-check` | Challenger mode. Stress-test positioning and claims. | - |

## Usage Notes

- **`/q-morning` is the only command you need to start a day.** It auto-checkpoints the previous session, catches missed debriefs, and loads canonical state. No need to run `/q-begin` or `/q-end` separately.
- **Debriefs happen automatically.** Paste a conversation transcript and Claude auto-runs `/q-debrief`. No command needed. If you forget, `/q-morning` catches missed debriefs the next day.
- `/q-begin`, `/q-end`, and `/q-checkpoint` still work if you want to use them manually, but they're no longer required.
- **`/q-draft` vs `/q-create`:** Use `/q-create` for structured deliverables (talk tracks, workflow packs). Use `/q-draft` for one-off outputs (specific email, DM, talking points for a meeting).
- **`/q-ingest-feedback [file]`** expects a file in `seed-materials/`. Place the file there first.
- **Modes are not sequential.** Switch freely. You can `/q-debrief` then immediately `/q-plan` then `/q-create`.

## Example Flows

### After a meeting:
1. `/q-debrief [person]` - process the conversation
2. `/q-calibrate` - update canonical files if positioning shifted
3. `/q-draft email [person]` - draft follow-up email

### Preparing for a meeting:
1. `/q-begin` - load current state
2. `/q-create talk-track [audience]` - generate tailored talk track
3. `/q-draft talking-points [person]` - person-specific prep

### Weekly planning:
1. `/q-begin` - load current state
2. `/q-plan` - review relationships and prioritize actions
3. `/q-create email [target]` - draft outreach for top priority

### Social engagement:

**Proactive mode (`/q-engage`):**
1. Pull Contacts DB for active prospects / investors / partners
2. For each target: Use Apify or browser to pull their last 7 days of posts. Run in parallel batches of 5.
3. Cross-reference with engagement tracker (last comment date - enforce 1 comment/person/week rule)
4. Filter to contacts who posted in last 48h AND haven't been engaged in 7+ days
5. For each post: generate 1 copy-paste ready comment (2-3 sentences, pool-appropriate style)
6. Output COPY-PASTE READY hitlist:
   ```
   ENGAGEMENT HITLIST (today) - [X] engagements, ~[X] min total

   1. [Name] - [Role] at [Company] ([pool])
      Post: "[first 120 chars of their post]..."
      Link: [post URL]
      Comment (copy-paste):
      "[ready-to-post comment, 2-3 sentences]"
      Energy: Quick Win | Time: 3 min
   ```
7. Cap at 5 engagements per hitlist (no overwhelm)
8. After founder confirms which comments they posted, log each to tracker

**Prospect outreach mode (`/q-engage dp-outreach`):**
For prospects who have NOT been contacted yet:
1. **Research** (parallel via Apify): Pull each prospect's profile data AND recent posts/activity. Extract what they post/comment about, specific recent posts, professional focus areas.
2. **Personalize**: For each prospect, craft Touch 1 comment (if they have recent posts), connection request (under 300 chars), follow-up DM (under 500 chars) with UTM-tagged link.
3. **Save** all messages to `output/design-partner/personalized-outreach-YYYY-MM-DD.md`
4. **Update CRM** contacts with research findings
5. **Output** execution sequence

**Rules for outreach personalization (MANDATORY):**
- Every message MUST reference something specific the person wrote, shared, or cares about
- Generic templates with only name/company swapped are NOT acceptable
- Use Apify for research (cheaper than Chrome). Fall back to Chrome only if Apify fails.

**Reactive mode (ad-hoc screenshot):**
When founder shares a social post screenshot at any time (no command needed):
1. **Identify** - Extract person name, role, company from screenshot
2. **Categorize** - Determine pool: VC | Design Partner | Prospect | Angel | Advisor | Connector | Practitioner
3. **Check CRM** - existing or new contact
4. **Generate 1 best comment** - The system picks the best style. No options to choose from, no decision paralysis. Founder can ask for alternatives if needed.
5. **Log to CRM** after founder confirms

**Rules (from `canonical/engagement-playbook.md`):**
- Never pitch your product in comments unless directly asked
- Max 3-4 sentences per comment
- One comment per person per week (unless they reply)
- Every engagement logged - no exceptions
- Comment style adapted to pool

### Process Improvement Auto-Post (TRIGGERED AUTOMATICALLY)

**Trigger:** Whenever Claude makes a process improvement during ANY session (new morning routine step, new automation, new CRM integration, new workflow, new command, system upgrade), Claude MUST auto-draft a social post about it before the session ends.

**What counts:** New steps, automations, workflows, CRM integrations, commands, engagement system upgrades, or anything that makes daily operations more efficient.

**Auto-draft format (save to `output/marketing/linkedin/linkedin-process-improvement-YYYY-MM-DD.md`):**
- Hook: What changed and why it matters (1 sentence)
- Context: The problem this solves for a solo/small-team founder (2-3 sentences)
- What I built: Specific description of the automation (3-4 sentences)
- Result: What my day looks like now vs before (1-2 sentences)
- Angle: AI-native founder building in public
- Tone: Honest, specific, vulnerable. Not "I'm so productive" but "here's how I cope"
- NO product pitch. This is about the founder journey.
- End with a question to drive comments

### Relationship Progression Engine (AUTOMATED)

The system fully manages prospect relationships. The founder only does two things:
1. Copy-paste the engagement actions from the morning hitlist
2. Report back what happened (or let the system auto-detect it)

Everything else is automated: logging, status updates, next-step generation, follow-up scheduling, escalation.

**Relationship ladder (each stage auto-advances to the next):**

```
STAGE 1: WARM UP (Status: Prospect)
  Actions: Comment on 2-3 of their posts over 1-2 weeks
  System generates: copy-paste comments in daily hitlist
  Advance trigger: 2-3 comments posted
  Auto-updates: Engagement tracker, Contact last contact date

STAGE 2: CONNECT (Status: Prospect)
  Actions: Send connection request (copy-paste from hitlist)
  System generates: personalized connection request referencing their content
  Advance trigger: Request accepted
  Auto-generates: Follow-up DM for Stage 3

STAGE 3: FIRST DM (Status: Outreach Sent)
  Actions: Send value-first DM (copy-paste from hitlist, no pitch)
  System generates: DM asking a genuine question about their work/pain
  Advance trigger: They reply
  Timeout: 10 days no reply = value-drop DM. 14 days = Cooling.

STAGE 4: CONVERSATION (Status: Outreach Sent)
  Actions: Continue DM conversation, aim toward a call
  System generates: reply suggestions based on what they said
  Advance trigger: Call scheduled

STAGE 5: DEMO/CALL (Status: Demo Done)
  Actions: Run the call, then debrief
  System generates: meeting prep, debrief prompt after
  Advance trigger: /q-debrief completed
```

**What the founder NEVER needs to do:**
- Report that they commented on someone's post (auto-detected in Step 3.8)
- Report that they sent a DM (auto-detected in Step 3.8)
- Report that they sent a connection request (auto-detected in Step 3.8)
- Report that they scheduled a call (auto-detected via calendar in Step 1)
- Check if connection requests were accepted (auto-detected in Step 3.8)
- Check if DMs got replies (auto-detected in Step 3.8)
- Remember to follow up on stale DMs (auto-generated value-drops)
- Track relationship stages (auto-advanced by the engine)
- Remember timeout rules (auto-enforced)
- Decide what to say next (auto-generated, copy-paste ready)
- Run /q-wrap then /q-handoff separately (auto-chained)
- Remember which lead sourcing queries to run (auto-rotated)

---

## Morning Briefing (`/q-morning`)

**Step 0 - Session bootstrap (runs before everything else):**

> **MANDATORY:** Before executing ANY step, read `.q-system/preflight.md`. It contains the tool manifest, known issues, session budget, and step logging format.

> **HARNESS RULE:** Every step must end with a call to the log helper. Replace DATE with today's date in every call.
> ```bash
> # Log a completed step:
> bash q-system/.q-system/log-step.sh DATE step_id done "result summary"
> # Log a failed step:
> bash q-system/.q-system/log-step.sh DATE step_id failed "" "error message"
> # Log a skipped step:
> bash q-system/.q-system/log-step.sh DATE step_id skipped "" "reason"
> # Log a partially completed step:
> bash q-system/.q-system/log-step.sh DATE step_id partial "what completed"
> # Add an action card:
> bash q-system/.q-system/log-step.sh DATE add-card C1 linkedin_comment "Person Name" "Draft text..." "https://url"
> # Run a gate check:
> bash q-system/.q-system/log-step.sh DATE gate-check step_8 true ""
> # Record state checksums:
> bash q-system/.q-system/log-step.sh DATE checksum-start field_name value
> bash q-system/.q-system/log-step.sh DATE checksum-end field_name value
> # Mark all cards as delivered:
> bash q-system/.q-system/log-step.sh DATE deliver-cards
> ```
> **No step is complete until `log-step.sh` runs.** The helper writes to disk. Context rot cannot affect it.

This step replaces the need to manually run `/q-begin` or `/q-end`. The founder only needs `/q-morning`.

- **0f - Server connectivity check (FAIL-FAST, RUNS FIRST):** See preflight.md Section 1 for exact tests. Test all configured MCP servers. Print pass/fail table. If any critical server fails, create the log and record the failure, then HALT. Non-critical failures: ask founder before proceeding.

- **0a - Checkpoint previous session + clean working memory + catch missed wraps:**
  Run a lightweight `/q-checkpoint`. Delete files in `memory/working/` older than 48 hours (except predictions.jsonl). Read `memory/last-handoff.md` for prior session context. **MISSED WRAP DETECTION (A2):** If handoff note is missing or older than 24h AND there were canonical file changes yesterday, run a lightweight retroactive wrap. No guilt, no pressure, just capture what happened. **MID-MORNING RESUME:** If the handoff note says "morning routine split - data collected through Step X", skip to Step 11.

- **0b - Missed debrief detection + unconfirmed action cards from last session:**
  Find the most recent previous morning log. Read its `action_cards` for any with `founder_confirmed: false`. Ask: "Last session I drafted these for you. Which ones did you actually do?" For each confirmed: update state. For each not done: carry forward.
  Also check `verification_queue` for unverified claims.
  **Then:** Cross-reference recent calendar events against CRM. Any meeting with an external person that has no matching interaction = missed debrief. Prompt founder.

- **0c - Load canonical state + snapshot state checksums:**
  Read all canonical files. Snapshot key state file fields via `log-step.sh checksum-start`.

- **0d - Load voice skill:**
  Read `.claude/skills/founder-voice/references/voice-dna.md` and `writing-samples.md`. ALL written output for the rest of the session must pass through the voice skill rules. Not optional.

- **0e - Load executive function skill (if AUDHD mode enabled):**
  Read `.claude/skills/audhd-executive-function/SKILL.md`. This skill governs how ALL output is structured. Every action item must be copy-paste ready. Not optional.

- **0g - Monthly checks (1st of month only):** Decision origin audit. Review `memory/monthly/` files. Prediction calibration. Outreach A/B analysis.

- **0h - Context budget strategy:** The morning routine is split into two halves. If context is running low after Step 5.9b, auto-run `/q-handoff` and tell the founder to start a new session.

**Context-saving rules (ENFORCED across all steps):**
- Never hold raw scraper results in context. Save to `output/lead-gen/` files immediately.
- Never generate content for the wrong day. Check the cadence schedule.
- Step 5.9 Phase 2: score in batches of 10. Discard sub-10 scores immediately.
- Step 5.9b: cap at 10 engagement targets.
- Meeting prep: only today's meetings get full prep.
- Steps 6-7 (compliance/freshness): skip if context < 40%.

After Step 0, the session is fully initialized.

**Step 1 - Parallel data pull:**
> **HARNESS:** Log EACH agent as a separate step: `1_calendar`, `1_gmail`, `1_notion_actions`, `1_notion_pipeline`.

- **Calendar agent:** Pull events for the current week. **NEW EVENT DETECTION (B4):** Cross-ref attendee names against CRM. If a calendar event exists with a known prospect AND no matching tracker entry: auto-detect as newly scheduled meeting. Auto-create Meeting Prep action.
- **Email agent:** Search inbox/sent for last 48 hours. Cross-ref against CRM contacts. **EMAIL CONVERSATION DETECTION (C4):** Check sent folder for outbound emails to prospects. For each, check inbox for replies. Auto-update contacts on reply. For unreturned emails 7+ days: note for channel death tracking.
- **CRM agent:** Pull overdue/due-today actions. Pull pipeline for upcoming follow-ups. **STALE ACTION CLEANUP (D5):** Auto-move any Actions with Due > 7 days past to Priority: Someday. Surface count without guilt.
- **Pipeline agent (optional):** Fetch pipeline data if available (local API, etc.)

**Step 1.5 - Warm intro path matching:**
- For new prospects: Cross-reference against existing contacts for warm intro paths
- **Rule:** Warm intro always beats cold outreach

**Step 2 - Meeting prep (TODAY's meetings get full prep, this-week gets one-line note):**
- **Apify:** Use profile/post scraper actors to pull attendee data
- **Fallback to Chrome:** Only if Apify fails
- **CRM:** Cross-reference attendee against Contacts + Interactions
- **For investor meetings:** Research the person, their fund, portfolio, thesis language

**Step 2.5 - X/Twitter activity review:**
- Use Apify to pull your own posts with engagement metrics and target accounts for reply targets
- Use Chrome for notifications and posting replies
- **Output:** New followers, replies to respond to, DM opportunities, QT/reply targets

**Step 3 - Social activity review:**
- Use Apify to pull your own recent posts with engagement data
- Use Chrome for checking comment-on-comment engagement
- Flag re-engagement opportunities and new post opportunities
- Cross-reference engagement tracker for follow-ups due

**Step 3.2 - Post-publish reconciliation:**
- Compare scraped social data against content pipeline. Auto-detect posts published outside the system.

**Step 3.5 - Prospect pipeline check:**
- Pull contacts for pipeline. Count by status.
- **Auto-close dead loops:** 3+ logged touches AND no response AND last touch > 14 days ago: automatically move to "Passed". No founder decision needed.
- If pipeline < target count: flag "Pipeline light - you could source more if you have energy"

**Step 3.7 - Content intelligence pull (weekly, Mondays):**
- Scrape own content across all platforms via Apify
- Analyze patterns, top/bottom performers
- Update `canonical/content-intelligence.md`

**Step 3.8 - Social DM + Connection Accept check (via Chrome):**
- **Part A - DM check (10-day lookback):** Read all visible DM threads
- **Part B - Connection Accept detection:** Check for recently accepted connection requests
- **Part C - Pending Connection Requests:** Flag old pending requests
- **Part D - Outbound action detection:** Auto-detect comments posted, DMs sent, connection requests sent. Auto-log and auto-advance relationship stages.
- **Auto-actions on detection:** When DM reply detected: update tracker, generate reply suggestion. When accept detected: advance to Stage 3, generate first DM. When DM needs reply: generate suggested reply.

**Step 4 - Content generation (DAY-SPECIFIC):**

**CONTEXT-SAVING: Only generate the content type assigned to today.**
- **Mon/Wed/Fri:** Signals/news posts + hot takes
- **Tue/Thu:** Thought leadership post. NO signals post.
- **Fri (additional):** Article draft

Before generating any content: Read `canonical/content-intelligence.md` for current patterns.

- **Fetch signals/news from {{YOUR_SIGNALS_SOURCE}}:** Pick 2-4 top items
- **Generate social posts** per platform templates
- **If Tue/Thu:** Also generate thought leadership posts from editorial calendar theme
- **If Fri:** Also generate article draft

**Step 4.1 - Value-first signal routing (daily):**
Send today's signals/news directly to people who would be AFFECTED by them. Not prospects, not a pitch. People who'd get real value.

- Match signals to contacts by industry, tools, role
- Generate copy-paste DM/email with specific links
- No pitch. Pure intel sharing. Max 1 per person per week.
- Log to engagement tracker after sending

**Step 4.5 - Marketing health check:**
- Asset freshness check
- Cadence check against weekly targets
- Stale drafts check

**Step 5 - Weekly site metrics (MONDAYS ONLY):**
- Pull analytics for last 7 days
- Compare to prior 7 days
- Check by channel

**Step 5.5 - Prospect engagement tracking (Mondays):**
- Pull UTM data from analytics
- Cross-reference with CRM contacts
- Identify who clicked vs who never clicked

**Step 5.8 - Prospect engagement scoring (daily):**
Stitch together ALL engagement signals into one score per active prospect.

| Signal | Points | Source |
|--------|--------|--------|
| Responded to DM | +5 | Step 3.8 |
| Replied to email | +5 | Step 1 |
| Commented on your post | +4 | Step 3 |
| Liked/reposted your post | +2 | Step 3 |
| Clicked UTM link | +2-4 | Step 5.5 |
| Accepted connection | +2 | Step 3.8 |
| Posted about your problem space | +3 | Step 5.9 |
| Outreach with no response | -1 per touch | Step 3.5 |
| No activity in 14+ days | -3 | Step 3.5 |

Tiers: Hot (8+), Warm (4-7), Cool (1-3), Cold (0 or negative).

**ENFORCE lead lifecycle rules** (from `canonical/lead-lifecycle-rules.md`):
- Channel death check: 3 unreturned messages on one channel = channel is dead. Suggest channel switch.
- Auto-park: 3 touches across 2+ channels + 14 days no response = move to Parked.
- Re-engagement cap: 60 days minimum before re-engaging Parked contacts unless a trigger fires.

**Step 5.9 - Lead sourcing (daily):**

**THIS STEP HAS 4 PHASES. DO NOT SKIP ANY.**

**PHASE 1 - COLLECT:** Run scraper actors to gather raw posts. Save all raw results to `output/lead-gen/`.

Run queries from a rotation schedule. **AUTO-ROTATION (C1):** Read `memory/morning-state.md` field `last_sourcing_day`. Auto-increment. Founder NEVER needs to remember which rotation day to use.

Define your query categories based on the pain surfaces your product addresses. Example categories:
- Category 1-N: One per major pain area your product solves
- Cross-category: Queries that span multiple pain areas (highest signal)

**PHASE 2 - QUALIFY AND RANK:** Claude reads every result, applies judgment. Process in batches of 10.

Score on 5 dimensions (1-5 each, max 25):
- Pain signal
- First-person proof
- Role fit
- Engagement opportunity
- Multi-team/multi-surface pain

Tiers: A (20-25) = Send today. B (15-19) = Engage today. C (10-14) = Warm list. Below 10 = Discard.

**PHASE 3 - PRODUCE OUTREACH:** Generate personalized outreach for Tier A and B prospects.
- Full post text required for each prospect
- Copy-paste connection requests
- Follow-up DM templates
- The "only for this person" test: Could this message be sent to anyone else? If yes, rewrite.
- Log predictions to `memory/working/predictions.jsonl`

**PHASE 4 - PIPELINE:** Create CRM entries for qualified prospects.

**RULES:**
- Max 5 new connection requests per day
- Connection requests reference THEIR words, not your product
- Full post text required - never write outreach from a summary
- Save raw results for trend analysis

**Step 5.9b - Daily Engagement Hitlist (daily, COPY-PASTE READY):**
- Pull engagement targets from CRM
- Scrape recent posts via Apify (cap at 10 targets)
- Generate copy-paste comments for each post found
- Also pull X/Twitter activity for contacts with X handles
- Must include all engagement types: LinkedIn comments, X replies, connection requests, Reddit comments
- **VALIDATION CHECKPOINT:** Before proceeding to Step 6, verify all 4 content types were attempted.
- Max 5 LinkedIn comments + 3 X replies + 5 connection requests + 2 Reddit comments per day

**Step 6 - Decision compliance check (SKIP if context is running low):**
- Read `canonical/decisions.md`, check all active RULE entries

**Step 7 - Positioning freshness check (SKIP if context is running low):**
- Check `memory/morning-state.md` for pending propagation

**Step 7.5 - Checkpoint drift detection:**
- Compare canonical file modification times against last checkpoint timestamp
- Auto-fix drift silently

**Step 8 - Output morning briefing:**

> **GATE CHECK (mandatory before starting Step 8):**
> Re-read morning log from disk. Verify all prior steps logged.

```
MISSED DEBRIEFS (only shown if any exist)

START HERE
[single task - highest-value, lowest-friction thing to do right now]

TODAY'S FOCUS (top 3-5 items, replaces scanning 15+ sections)
1. [action] - [why now] (Energy: Quick Win, 5 min)
2. [action] - [why now] (Energy: Quick Win, 10 min)
3. [action] - [why now] (Energy: Deep Focus, 20 min)

CALENDAR (this week)
MEETING PREP
UNLOGGED EMAILS (last 48h)
SOCIAL DMs + CONNECTIONS (auto-detected)
X ACTIVITY
ACTIONS DUE TODAY
PIPELINE
WARM INTRO OPPORTUNITIES
SOCIAL RE-ENGAGE
SIGNALS + POSTS
INTEL DROPS TO SEND
SITE METRICS (Mondays only)
PROSPECT TEMPERATURE (daily)
DAILY ENGAGEMENT HITLIST (COPY-PASTE READY)
PROBLEM-LANGUAGE PROSPECTS
MARKETING HEALTH
PUBLISH RECONCILIATION (only if changes)
DECISION COMPLIANCE
PENDING PROPAGATION
CHECKPOINT DRIFT (only if found)
INVESTOR UPDATE DUE (only if triggered)
```

**Step 8.5 - Pick the "Start Here" task:**
Select ONE task for the top. Priority order:
1. Missed debrief (memory decays fast)
2. Hot prospect responded
3. Meeting in the next 2 hours
4. Day-specific content task
5. Quick Win action with highest impact

**Step 9 - Offer fixes + push actions to CRM:**
> **GATE CHECK (mandatory).**
Create CRM Actions for every actionable item surfaced in the briefing.

**Step 9.5 - Investor update check:**
- Check if it's time to send an investor update (milestone triggers or 30+ days since last)

**Step 10 - Update daily checklists (if using Notion):**
- Daily Actions page with to-do checkboxes
- Daily Posts page with social post drafts

**Step 10.5 - Auto-sync CRM (A3):**
Push all changes from Steps 1-10 in one batch.

**Step 11 - Generate daily schedule JSON + build HTML + open in browser:**

> **GATE CHECK (mandatory).**

**HOW IT WORKS:** Claude writes a JSON data file. A build script injects it into a locked HTML template. Claude NEVER writes raw HTML.

1. Read the schema: `marketing/templates/schedule-data-schema.md`
2. Generate JSON: Write `output/schedule-data-YYYY-MM-DD.json`
3. Build HTML: `bash marketing/templates/build-schedule.sh output/schedule-data-YYYY-MM-DD.json output/daily-schedule-YYYY-MM-DD.html`
4. Open in browser
5. Telegram push (if configured)

**ACTIONABILITY RULES (ENFORCED - every item in HTML must pass these):**

**Rule A1:** NEVER use cross-references. Every checklist item must contain the actual copy-paste text inline.
**Rule A2:** EVERY checklist item must include the NEXT PHYSICAL ACTION.
**Rule A3:** EVERY pending CRM Action with Priority "Today" must appear in the HTML with a draft message.
**Rule A4:** ALL debriefs from the past 48 hours must produce follow-up items in the HTML.
**Rule A5:** Pipeline/temperature dashboards are INFORMATIONAL ONLY. They go in a collapsed section at the bottom.
**Rule A6:** For any risk signal, include the specific recovery action with draft text.
**Rule A7:** Items ordered by friction, lowest first.

The template (`daily-schedule-template.html`) is LOCKED. Never edit it during morning routine.

**Step 12 - Post-Execution Audit (MANDATORY):**

12a. Snapshot session-end state checksums
12b. Mark action cards as delivered
12c. Run the audit harness:
```bash
python3 q-system/.q-system/audit-morning.py q-system/output/morning-log-DATE.json
```
12d. Log Step 12 and update morning-state.md
12e. Recovery if audit verdict is not COMPLETE

---

## MCP Tools

Configure your MCP tools in `settings.json`. Common tools used:
- **Google Calendar:** `mcp__claude_ai_Google_Calendar__gcal_list_events`
- **Gmail:** `mcp__claude_ai_Gmail__gmail_search_messages`, `mcp__claude_ai_Gmail__gmail_read_message`
- **Notion:** `mcp__notion__*` or `mcp__notion_api__*` (check which server connects to your workspace)
- **Apify** (primary for data scraping): LinkedIn, Twitter/X, Reddit, Medium scraping
- **Chrome** (interactive + DMs): LinkedIn DM reading, posting comments, checking notifications, analytics
- **NotebookLM:** Research notebooks, Q&A over stored content
- **Gamma:** Deck and social card generation

---

### Content Intelligence (`/q-content-intel`)

> Scrape your own content across all platforms. Analyze what works vs. what doesn't.

**Full run (weekly or on demand):**
1. Scrape all platforms via Apify
2. Normalize and rank by engagement rate
3. Extract patterns (top/bottom 20%, theme analysis, timing analysis, hook analysis)
4. Update `canonical/content-intelligence.md`
5. Generate recommendations

**Quick score (on demand):** Score any draft 1-5 on hook strength, pattern match, platform fit, timing, novelty.

---

### Investor Update (`/q-investor-update`)

**When to run:** After a milestone, or on 30-day calendar trigger.

1. Pull pipeline, milestones, recent wins
2. Draft under 300 words. Lead with strongest proof point.
3. Generate variants per recipient type (active pipeline, thesis nod, connectors)
4. Save and track

---

### Marketing Commands (`/q-market-*`)

**`/q-market-plan`** - Weekly content planning
**`/q-market-create [type] [topic]`** - Content generation
**`/q-market-review [file]`** - Content validation
**`/q-market-publish [file]`** - Mark published
**`/q-market-assets`** - Asset refresh
**`/q-market-status`** - Marketing snapshot

See `marketing/README.md` for full details.

---

### `/q-checkpoint` - Auto-save canonical state

1. Snapshot canonical file state
2. Verify consistency (decision compliance check)
3. Log to `my-project/progress.md`
4. Update `memory/morning-state.md` checkpoint timestamp

### `/q-end` - End session

1. Run `/q-checkpoint`
2. Session summary: files modified, CRM updates, open items

---

### Evening Wrap (`/q-wrap`)

10-minute end-of-day system health check:

1. **Effort log** (2 min): Count actions taken today. Track effort, not outcomes.
2. **Unfinished actions triage** (3 min): What carries over? What's stale? No guilt.
3. **Debrief check** (1 min): Any meetings without debriefs?
4. **Canonical drift check** (2 min): Any insights not yet in canonical files?
5. **Tomorrow preview** (2 min): Calendar + prep status.

After wrap (all automatic): auto-checkpoint, promote working memory, clean stale files, **auto-run `/q-handoff`**.

---

### Session Handoff (`/q-handoff`)

Generates context note at `memory/last-handoff.md`.

**When to trigger:** User says "done", context >80%, after `/q-wrap`, before compaction.

---

### Reality Check (`/q-reality-check`)

Challenger mode. Stress-tests current positioning against evidence.

1. Read all canonical files
2. Challenge positioning, traction, and market claims
3. Rate each claim: STRONG / MODERATE / WEAK
4. For WEAK: suggest a specific validation experiment
5. Output the hardest question someone will ask that you can't answer yet

Run monthly or before major meetings.

---

### Prediction Tracking

Log predictions about outreach outcomes to `memory/working/predictions.jsonl`:
```jsonl
{"date":"YYYY-MM-DD","prospect":"Name","channel":"linkedin_dm","prediction":"will_reply","confidence":0.7,"style":"V1","outcome":null,"outcome_date":null}
```

Style codes: V1 (value drop), Q1 (question), P1 (peer observation), C1 (content reference), W1 (warm intro).

Monthly: calculate reply rate per style, shift toward best performers.

---

### Predict-First Prompting (Debriefs)

Before the founder describes a conversation, the system predicts:
- Top 3 likely objections surfaced
- Top 3 likely topics discussed
- Predicted relationship outcome (warmer/cooler/same)

After the founder describes it, compare. Wrong predictions reveal gaps in canonical files.

---

### Memory Management

```
memory/
  working/          # Session-scoped, ephemeral (<48h)
  weekly/           # 7-day rolling window
  monthly/          # Persistent insights
  last-handoff.md   # Session handoff note
  morning-state.md  # Morning routine state tracker
  marketing-state.md # Marketing system state
  graph.jsonl       # Entity-relationship knowledge graph
```

**Lifecycle:**
- `working/` -> cleaned during `/q-morning` Step 0a or promoted during `/q-wrap`
- `weekly/` -> reviewed Monday mornings, promoted or archived
- `monthly/` -> reviewed 1st of month, promoted to canonical if proven

---

### Graph Knowledge Base

Structured triples in `memory/graph.jsonl`:
```jsonl
{"s":"Person Name","p":"works_at","o":"Company","t":"YYYY-MM-DD"}
{"s":"Person Name","p":"cares_about","o":"topic","t":"YYYY-MM-DD"}
{"s":"Connector","p":"introduced","o":"Person Name","t":"YYYY-MM-DD"}
```

Written during debriefs and lead sourcing. Queried via grep.

---

### Fail-Fast Mode (ENFORCED)

Step 0f runs FIRST. If ANY critical server fails, STOP the entire routine and report. Non-critical failures: ask founder before proceeding.

This also applies to failures MID-ROUTINE. If any step fails: STOP, report what broke, report what completed, report what data was collected so far.

No partial briefings. No silent skipping. No substituting missing data.

---

### Decision Origin Tagging

All decisions in `canonical/decisions.md` must include origin tags:
- `[USER-DIRECTED]`, `[CLAUDE-RECOMMENDED -> APPROVED/MODIFIED/REJECTED]`, `[SYSTEM-INFERRED]`

Monthly audit (1st of month): flag if >60% are rubber-stamped approvals.

---

### Inter-Skill Review Gates

Before outputting factual claims about the founder's product:
1. Check canonical files (current-state.md, talk-tracks.md)
2. If not found: mark `{{UNVALIDATED}}`
3. If contradicts canonical: BLOCK output
