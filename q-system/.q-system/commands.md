# Q Instance Commands

> These are conventions for interacting with the Q Entrepreneur OS. Use them as natural language triggers — they tell Claude which mode to enter and what to do.

| Command | Purpose | Mode |
|---------|---------|------|
| `/q-begin` | Start a new session. Claude reads all canonical files first to load current state. | — |
| `/q-status` | Report current state from `my-project/progress.md`. Quick snapshot of where things stand. | — |
| `/q-calibrate` | Enter Calibrate mode. Update canonical files based on new information, feedback, or market changes. | CALIBRATE |
| `/q-create [type] [audience]` | Enter Create mode. Generate a specific output (talk track, email, slide text, diagram, memo) for a specific audience. | CREATE |
| `/q-debrief [person]` | Enter Debrief mode. Use the structured debrief template to process a conversation. Includes 12 strategic implications lenses, market intelligence routing, and **Design Partner Conversion** (mandatory for practitioner/CISO calls - produces copy-paste message to convert conversation into trial). **Highest-priority workflow.** | DEBRIEF |
| `/q-plan` | Enter Plan mode. Review relationships, objections, and proof gaps. Propose prioritized next actions. | PLAN |
| `/q-draft [type] [audience]` | Generate an ad-hoc output to `output/drafts/`. For one-off emails, DMs, talking points. Ephemeral. | CREATE |
| `/q-ingest-feedback [file]` | Process a feedback file from `q-system/output/`. Extract objections, resonance phrases, competitive intel, market intelligence, and contact context into canonical files. Also evaluates for market intelligence (problem language, category signals, objection previews, competitive intel, buyer process, narrative validation) and routes to `canonical/market-intelligence.md`. | CALIBRATE |
| `/q-checkpoint` | Save current canonical state. Verify all files are consistent. Log to `my-project/progress.md`. Update `memory/morning-state.md` checkpoint timestamp. | — |
| `/q-end` | End session. Auto-runs `/q-checkpoint` first, then summarizes all changes. | — |
| `/q-sync-notion` | Sync local files ↔ Notion CRM. Push new contacts/interactions/pipeline changes to Notion. Pull follow-up date changes and status updates from Notion back to local files. | CALIBRATE |
| `/q-morning` | Morning briefing. Runs calendar + email + Notion checks in parallel, surfaces unlogged interactions, checks decision rule compliance, flags stale positioning. See workflow below. | — |
| `/q-engage` | LinkedIn engagement mode. Proactive: generate daily hitlist from Notion targets. Reactive: user shares post screenshot → comment suggestions + auto-log to Notion. See workflow below. | CREATE |
| `/q-content-intel` | Content intelligence. Scrape own content across all platforms (Chrome for LinkedIn, Reddit MCP for Reddit, RSS for Medium/Substack, Apify for X only). Analyze what works vs. doesn't. Update `canonical/content-intelligence.md`. Cross-reference themes against `canonical/market-intelligence.md` to check if our content topics align with what the market is discussing. Score drafts before publishing. | CALIBRATE |
| `/q-investor-update` | Draft a milestone-triggered investor update email for the full VC list. Pulls pipeline, recent wins, metrics. Batch send-ready. | CREATE |
| `/q-market-plan` | Weekly content planning. Reads theme rotation + editorial calendar. Generates this week's plan. Creates Notion entries in Content Pipeline + Editorial Calendar DBs. | CREATE |
| `/q-market-create [type] [topic]` | Generate marketing content. Types: linkedin, x, medium, substack, one-pager, outreach, deck, follow-up, reddit, investor-update. Reads canonical files + templates + NotebookLM. Runs guardrails. For deck/one-pager, generates via Gamma MCP. See workflow below. | CREATE |
| `/q-market-review [file]` | Validate content against `marketing/content-guardrails.md`. PASS/FAIL with specific fixes. | — |
| `/q-market-publish [file]` | Mark content published. Update Content Pipeline DB status. Log to `memory/marketing-state.md` publish log. | — |
| `/q-market-assets` | Refresh all reusable assets in `marketing/assets/` from canonical files. Flag stale items. Flag Gamma decks needing re-generation. Update Asset Library DB. | CALIBRATE |
| `/q-market-status` | Quick snapshot: Content Pipeline counts, cadence progress, asset health, Gamma deck status. | — |
| `/q-wrap` | Evening wrap. 10-min end-of-day system health check. Closes open loops, catches missed debriefs, previews tomorrow. | — |
| `/q-handoff` | Session handoff. Generates context note for next session. Run before ending or when context is running low. | — |
| `/q-reality-check` | Challenger mode. Stress-tests current positioning, claims, and assumptions against evidence. | — |
| `/q-research [topic]` | Anti-hallucination research mode. Every claim must cite a source (local file, web search snippet, named paper). Uses a 4-level cascade: local files first, then search snippets, then full page fetch, then Scholar Gateway. Token-budgeted (5 searches, 3 fetches max per question). Say "exit research mode" to return to normal. | — |

## Usage Notes

- **`/q-morning` is the only command you need to start a day.** It auto-checkpoints the previous session, catches missed debriefs, and loads canonical state. No need to run `/q-begin` or `/q-end` separately.
- **Debriefs happen automatically.** Paste a conversation transcript and Claude auto-runs `/q-debrief`. No command needed. If you forget, `/q-morning` catches missed debriefs the next day.
- `/q-begin`, `/q-end`, and `/q-checkpoint` still work if you want to use them manually, but they're no longer required.
- **`/q-draft` vs `/q-create`:** Use `/q-create` for structured deliverables (talk tracks, workflow packs). Use `/q-draft` for one-off outputs (specific email, DM, talking points for a meeting).
- **`/q-ingest-feedback [file]`** expects a file in `q-system/output/`. Place the file there first.
- **Modes are not sequential.** Switch freely. You can `/q-debrief` then immediately `/q-plan` then `/q-create`.

## Example Flows

### After a VC meeting:
1. `/q-debrief [VC name]` - process the conversation
2. `/q-calibrate` - update canonical files if positioning shifted
3. `/q-draft email [VC name]` - draft follow-up email

### After a practitioner/CISO/design partner conversation:
1. Paste transcript - debrief auto-runs (template + 12 lenses + routing)
2. Design Partner Conversion auto-runs: maps their pain to current capabilities, identifies gaps, drafts copy-paste message to convert them to a trial
3. Founder sends the message (copy-paste from output)
4. Follow-up Action auto-created in Notion (5 days out)

### Preparing for a CISO meeting:
1. `/q-begin` — load current state
2. `/q-create talk-track CISO` — generate tailored talk track
3. `/q-draft talking-points [CISO name]` — person-specific prep

### Weekly planning:
1. `/q-begin` — load current state
2. `/q-plan` — review relationships and prioritize actions
3. `/q-create email [target]` — draft outreach for top priority

### LinkedIn engagement:

**Proactive mode (`/q-engage`):**
1. Pull Contacts DB for Type = VC, Design Partner, CISO, Advisor, Connector with Status = Active or Warm or Design Partner Status = Prospect
2. For each target: Use Chrome browser to navigate to each target's LinkedIn profile and read their recent posts (last 7 days). Process sequentially (one browser tab).
3. Cross-reference with Notion LinkedIn Tracker (last comment date - enforce 1 comment/person/week rule)
4. Filter to contacts who posted in last 48h AND haven't been engaged in 7+ days
5. For each post: evaluate for **market intelligence** first (same lenses as Step 2.5 in lead sourcing - problem language, category signal, objection preview, competitive intel, buyer process, narrative check). If the post has canonical value, log to `canonical/market-intelligence.md` before generating engagement copy. This applies to ALL posts read, not just ones we comment on.
6. Generate 1 copy-paste ready comment per target (2-3 sentences, pool-appropriate style)
7. Output COPY-PASTE READY hitlist:
   ```
   ENGAGEMENT HITLIST (today) - [X] engagements, ~[X] min total

   1. [Name] - [Role] at [Company] ([pool])
      Post: "[first 120 chars of their post]..."
      Link: [LinkedIn post URL]
      Comment (copy-paste):
      "[ready-to-post comment, 2-3 sentences]"
      Energy: Quick Win | Time: 3 min

   2. [Name] - [Role] at [Company] ([pool])
      Post: "[first 120 chars of their post]..."
      Link: [LinkedIn post URL]
      Comment (copy-paste):
      "[ready-to-post comment, 2-3 sentences]"
      Energy: Quick Win | Time: 3 min
   ```
8. Cap at 5 engagements per hitlist (ADHD-friendly, no overwhelm)
9. After founder confirms which comments they posted, log each to Notion LinkedIn Tracker

**Design Partner outreach mode (`/q-engage dp-outreach`):**

For prospects with DP Status = Prospect who have NOT been contacted yet:
1. **Research** (via Chrome): Navigate to each prospect's LinkedIn profile via Chrome browser. Read their profile data AND recent posts/activity. Extract:
   - What they post/comment about (topics, themes, pain points)
   - Specific recent posts (quotes, subjects)
   - Professional focus areas and what they care about
   - Any angles connecting to {{YOUR_PRODUCT}}'s positioning
2. **Personalize** using the `cold-email` marketing skill and `marketing/templates/cold-outreach.md` template: For each prospect, craft:
   - Touch 1 comment (if they have recent posts to comment on)
   - Connection request (under 300 chars) referencing something specific from their activity
   - Follow-up DM (under 500 chars) referencing their specific work, asking a genuine question, with UTM-tagged demo link as async CTA (e.g., `demo.{{YOUR_DOMAIN}}?utm_source=linkedin&utm_medium=dm&utm_campaign=cold-outreach&utm_content=[prospect-slug]`)
3. **Save** all messages to `output/design-partner/personalized-outreach-YYYY-MM-DD.md`
4. **Update Notion** contacts with research findings (What They Care About, Follow-up Action, Strategic Value)
5. **Output** execution sequence (who to contact first, Touch 1 vs Touch 2)

**Rules for DP outreach personalization (MANDATORY):**
- Every message MUST reference something specific the person wrote, shared, spoke about, or cares about
- Generic templates with only name/company swapped are NOT acceptable
- Use Chrome browser for all LinkedIn research. Navigate to each prospect's profile to read their activity and posts.
- The `cold-email` marketing skill must be invoked for message generation
- Playbook details in `output/design-partner/cold-prospecting-playbook.md`

**Reactive mode (ad-hoc screenshot):**
When founder shares a LinkedIn post screenshot at any time (no command needed):
1. **Identify** — Extract person name, role, company from screenshot
2. **Categorize** — Determine pool: VC | Design Partner | CISO | Angel | Advisor | Connector | Practitioner
3. **Check Notion** — Search Contacts DB. If exists, pull history. If new, flag for creation.
4. **Market intelligence check** — Before generating a comment, evaluate the POST CONTENT for canonical value using the same 6 lenses from Step 2.5 (problem language, category signal, objection preview, competitive intel, buyer process, narrative check). If the post has canonical value, log to `canonical/market-intelligence.md`. This happens regardless of whether we comment.
5. **Generate 1 best comment** — The system picks the best style (Insight / Connector / Question) based on pool, context, and post content. No options to choose from, no decision paralysis. If the founder wants alternatives, they can ask. Grounded in:
   - The post's actual content
   - {{YOUR_PRODUCT}}'s canonical positioning
   - Person's pool and what matters to them
   - Prior interaction history (if any)
6. **Log to Notion** (after founder picks a comment):
   - If NEW person: Create Contact (Name, Role, Company, Type=pool, Status=Warm) + LinkedIn Tracker entry (Type=Comment, post summary, comment posted, Date=today)
   - If EXISTING person: Create LinkedIn Tracker entry linked to Contact, update Last Contact date
   - Set Follow-up Date: 5-7 days out on LinkedIn Tracker entry

**Rules (from `canonical/engagement-playbook.md`):**
- Never pitch {{YOUR_PRODUCT}} in comments unless directly asked
- Max 3-4 sentences per comment
- One comment per person per week (unless they reply)
- Every engagement logged to Notion — no exceptions
- Comment style adapted to pool (VCs get domain insight, practitioners get peer validation)

### Process Improvement Auto-Post (TRIGGERED AUTOMATICALLY)

**Trigger:** Whenever Claude makes a process improvement during ANY session (new morning routine step, new automation, new Notion integration, new workflow, new command, system upgrade), Claude MUST auto-draft a LinkedIn + X post about it before the session ends.

**What counts as a process improvement:**
- New step added to morning routine
- New automation or workflow built
- New Notion DB, field, or integration
- New command added to commands.md
- Relationship engine or engagement system upgrade
- Any change that makes the founder's daily operations more efficient

**Auto-draft format:**

LinkedIn post (save to `output/marketing/linkedin/linkedin-process-improvement-YYYY-MM-DD.md`):
- Hook: What changed and why it matters (1 sentence, pattern-interrupt)
- Context: The problem this solves for a solo/small-team founder (2-3 sentences)
- What I built: Specific description of the automation, no jargon (3-4 sentences)
- Result: What my day looks like now vs before (1-2 sentences)
- Angle: AI-native founder building in public. "This is what building a startup looks like when your co-founder is an AI."
- Tone: Honest, specific, vulnerable. Not "I'm so productive" - more "I have ADHD and this is how I cope with running a startup."
- NO {{YOUR_PRODUCT}} pitch. This is about the founder journey, not the product.
- End with a question to drive comments (e.g., "What's the most tedious part of your workflow that you wish was automated?")

X post (save to same file):
- 1-2 sentences, punchier version of the LinkedIn hook
- "Just automated [thing]. My morning routine now does [result] while I drink coffee."
- Link to LinkedIn post if it's a good one

**Voice rules for process improvement posts:**
- First person, casual, specific numbers when possible
- Show the before/after ("I used to spend 45 min finding posts to comment on. Now it's copy-paste.")
- ADHD angle is a strength, not a weakness ("My brain can't track 50 follow-ups. So I built a system that does.")
- Reference AI as a tool, not magic ("Claude generates the comments. I decide which ones sound like me.")

**After drafting:** Add to Daily Posts page in Notion as a to-do item. Tag as "Process Improvement" in the draft file.

### Relationship Progression Engine (AUTOMATED)

The system fully manages prospect relationships. The founder only does two things:
1. Copy-paste the engagement actions from the morning hitlist
2. Report back what happened (e.g., "commented on Chris Long's post", "Paul accepted my request", "Aaron replied")

**Everything else is automated:** logging, status updates, next-step generation, follow-up scheduling, escalation.

**Relationship ladder (each stage auto-advances to the next):**

```
STAGE 1: WARM UP (DP Status: Prospect)
  Actions: Comment on 2-3 of their posts over 1-2 weeks
  System generates: copy-paste comments in daily hitlist
  Advance trigger: Founder says "commented on [name]'s post" x2-3
  Auto-updates: LinkedIn Tracker (Type: Comment), Contact Last Contact date

STAGE 2: CONNECT (DP Status: Prospect)
  Actions: Send connection request (copy-paste from hitlist)
  System generates: personalized connection request referencing their content
  Advance trigger: Founder says "[name] accepted my request"
  Auto-updates: LinkedIn Tracker (Type: Connection Request, Status: Responded), Contact Last Contact date
  Auto-generates: Follow-up DM for Stage 3 (copy-paste ready, queued for next day)

STAGE 3: FIRST DM (DP Status: Outreach Sent)
  Actions: Send value-first DM (copy-paste from hitlist, no pitch)
  System generates: DM asking a genuine question about their work/pain
  Advance trigger: Founder says "[name] replied to my DM"
  Auto-updates: LinkedIn Tracker (Type: Outreach DM, Status: Responded), DP Status to Outreach Sent, Contact Last Contact date
  Auto-generates: Reply DM for Stage 4

  Timeout: If no reply after 10 days, system generates a value-drop DM (share a relevant signal)
  Timeout 2: If no reply after 14 days total (2 touches), move to Cooling. System stops generating actions.

STAGE 4: CONVERSATION (DP Status: Outreach Sent)
  Actions: Continue DM conversation, aim toward a call
  System generates: reply suggestions based on what they said
  Advance trigger: Founder says "scheduled a call with [name]" or "demo booked with [name]"
  Auto-updates: Contact Status to Active, creates Calendar prep action
  Auto-generates: Meeting prep brief (from their profile + posts + what they care about)

STAGE 5: DEMO/CALL (DP Status: Demo Done)
  Actions: Run the call, then debrief
  System generates: meeting prep in morning briefing, debrief prompt after
  Advance trigger: Founder runs /q-debrief
  Auto-updates: DP Status to Demo Done, creates Interaction in Notion, generates follow-up email
```

**Founder reporting protocol (what to say after doing things):**

The founder can report in natural language. The system parses and auto-updates everything.
Most actions are AUTO-DETECTED by Step 3.8 - the founder only needs to report posting comments and sending messages.

| What founder says | System does | Auto-detected? |
|---|---|---|
| ~~"commented on [name]'s post"~~ | ~~Log LinkedIn Tracker (Comment), update Last Contact~~ | **YES - auto-detected in Step 3.8 Part D** |
| ~~"sent connection request to [name]"~~ | ~~Log LinkedIn Tracker (Connection Request)~~ | **YES - auto-detected in Step 3.8 Part D** |
| ~~"sent DM to [name]"~~ | ~~Log LinkedIn Tracker (Outreach DM)~~ | **YES - auto-detected in Step 3.8 Part D** |
| ~~"scheduled call with [name]"~~ | ~~Update Status to Active, create Meeting Prep~~ | **YES - auto-detected in Step 1 calendar check (see B4)** |
| ~~"[name] accepted"~~ | ~~Update LinkedIn Tracker, generate Stage 3 DM~~ | **YES - auto-detected in Step 3.8 Part B** |
| ~~"[name] replied"~~ | ~~Update LinkedIn Tracker, generate reply~~ | **YES - auto-detected in Step 3.8 Part A** |
| "[name] went cold" or "skip [name]" | Move to Cooling/Cold/Passed, remove from hitlist | NO - must report |

**What the founder NEVER needs to do:**
- Report that they commented on someone's post (auto-detected in Step 3.8 Part D)
- Report that they sent a DM (auto-detected in Step 3.8 Part D)
- Report that they sent a connection request (auto-detected in Step 3.8 Part D)
- Report that they scheduled a call (auto-detected via calendar in Step 1)
- Check if connection requests were accepted (auto-detected in Step 3.8 Part B)
- Check if DMs got replies (auto-detected in Step 3.8 Part A)
- Remember to follow up on stale DMs (auto-generated value-drops)
- Track relationship stages (auto-advanced by the engine)
- Remember timeout rules (auto-enforced)
- Decide what to say next (auto-generated, copy-paste ready)
- Run /q-wrap then /q-handoff separately (auto-chained)
- Remember which lead sourcing queries to run (auto-rotated)

**Morning routine integration (Step 5.9b additions):**

During the daily engagement hitlist generation, the system also:
1. **Checks LinkedIn Tracker for pending follow-ups** (Follow-up Date = today or overdue)
2. **Checks for connection request timeouts** (Sent 7+ days ago, no response - generate reminder or move to next)
3. **Checks for DM timeouts** (Sent 7+ days ago, no reply - generate value-drop DM)
4. **Checks for stage readiness** (2+ comments logged - ready for connection request)
5. **Generates the NEXT action for each active prospect** based on their current stage

**Daily hitlist now includes RELATIONSHIP ACTIONS section:**
```
💬 DAILY ENGAGEMENT HITLIST

RELATIONSHIP ACTIONS (auto-generated from progression engine):

  🔄 READY TO CONNECT (commented 2+ times, no connection request yet):
  1. [Name] - you commented on 3 posts over 2 weeks. Time to connect.
     🔗 [LinkedIn profile URL]
     💬 Copy-paste connection request:
     "[personalized request]"
     ⏱️ 2 min | Quick Win

  📩 FOLLOW-UP DMs DUE (connection accepted, DM not yet sent):
  1. [Name] - accepted your request 2 days ago. Send first DM.
     💬 Copy-paste DM:
     "[value-first DM, genuine question about their work]"
     ⏱️ 3 min | Quick Win

  🔁 VALUE-DROP DMs (first DM sent 7+ days ago, no reply):
  1. [Name] - no reply to first DM (sent Mar 2). Send value drop.
     💬 Copy-paste DM:
     "Saw [relevant signal]. Given your work on [their thing], thought worth flagging: [UTM link]"
     ⏱️ 3 min | Quick Win

  💬 REPLIES TO CONTINUE (they responded to your DM):
  1. [Name] said: "[their reply summary]"
     💬 Suggested reply:
     "[continue conversation, aim toward call]"
     ⏱️ 5 min | Quick Win

  NEW COMMENTS (warming up new prospects):
  [regular comment hitlist as before]
```

**Notion updates (all automatic, founder does nothing):**

When founder reports an action, the system immediately:
1. Creates LinkedIn Tracker entry (Title, Type, Status, Date, Content Summary, Target Contact relation, Follow-up Date)
2. Updates Contact's Last Contact date
3. Updates Contact's Follow-up Action to the next step
4. Updates Contact's Design Partner Status if stage changed
5. Updates Contact's Status if needed (e.g., Warm -> Active)
6. Creates next Action in Actions DB (Energy: Quick Win, Time Est: 3 min or 5 min)

### Notion sync (weekly or after batch updates):
1. `/q-sync-notion` — push local changes to Notion, pull Notion changes to local
   - **Local → Notion:** New debriefs → Interactions, updated contacts → Contact properties, pipeline changes → Investor Pipeline
   - **Notion → Local:** Follow-up dates changed in Notion → relationships.md, pipeline stage changes → current-state.md
   - **Notion IDs:** See `my-project/progress.md` entry "2026-02-27 — Notion Founder CRM Built" for all database data_source_ids

### Morning briefing (`/q-morning`):

**Step 0 — Session bootstrap (runs before everything else):**

> **MANDATORY:** Before executing ANY step, read `.q-system/preflight.md`. It contains the tool manifest, known issues, session budget, and step logging format.

> **HARNESS RULE:** Every step must end with a call to the log helper. Replace DATE with today's date in every call.
> ```bash
> # Log a completed step:
> python3 q-system/.q-system/log-step.py DATE step_id done "result summary"
> # Log a failed step:
> python3 q-system/.q-system/log-step.py DATE step_id failed "" "error message"
> # Log a skipped step:
> python3 q-system/.q-system/log-step.py DATE step_id skipped "" "reason"
> # Log a partially completed step:
> python3 q-system/.q-system/log-step.py DATE step_id partial "what completed"
> # Add an action card (for any founder-facing draft):
> python3 q-system/.q-system/log-step.py DATE add-card C1 linkedin_comment "Person Name" "Draft text..." "https://url"
> # Run a gate check (at Steps 8, 9, 11):
> python3 q-system/.q-system/log-step.py DATE gate-check step_8 true ""
> # Record state checksums:
> python3 q-system/.q-system/log-step.py DATE checksum-start field_name value
> python3 q-system/.q-system/log-step.py DATE checksum-end field_name value
> # Mark all cards as delivered (after Step 11 HTML opens):
> python3 q-system/.q-system/log-step.py DATE deliver-cards
> ```
> **No step is complete until `log-step.py` runs.** The helper writes to disk. Context rot cannot affect it.

This step replaces the need to manually run `/q-begin` or `/q-end`. The founder only needs `/q-morning`.

- **0f - Server connectivity check (FAIL-FAST, RUNS FIRST):** See preflight.md Section 1 for exact tests. After all checks pass:
  ```bash
  python3 q-system/.q-system/log-step.py DATE init
  python3 q-system/.q-system/log-step.py DATE 0f_connection_check done "7/7 passed"
  ```
  If any critical server fails, still create the log and record the failure:
  ```bash
  python3 q-system/.q-system/log-step.py DATE init
  python3 q-system/.q-system/log-step.py DATE 0f_connection_check failed "" "Notion API: property not found"
  ```
  Then HALT.

- **0a - Checkpoint previous session + clean working memory + check for mid-morning resume + catch missed wraps:**
  > Log: `python3 q-system/.q-system/log-step.py DATE 0a_checkpoint done "SUMMARY"` Run a lightweight `/q-checkpoint` (snapshot canonical files, log to progress.md, update checkpoint timestamp). If this is a fresh session with no changes, skip gracefully. Also: delete any files in `memory/working/` older than 48 hours (except predictions.jsonl which is append-only). Read `memory/last-handoff.md` for prior session context - use this to understand what was in progress. **MISSED WRAP DETECTION (A2):** If `memory/last-handoff.md` is missing or older than 24h AND there were canonical file changes yesterday (check mtimes), a wrap was missed. Run a lightweight retroactive wrap: count yesterday's Actions marked complete, note any unfinished items, log to progress.md with "[Auto-recovered from missed wrap]". No guilt, no pressure, just capture what happened. **MID-MORNING RESUME:** If the handoff note says "morning routine split - data collected through Step X", skip Steps 0b-5.9b and jump directly to Step 11 (JSON generation). The handoff note contains all collected data needed for the JSON. This prevents re-running 45 min of data collection.
- **0b - Action card pickup + missed debrief detection:**
  **HARNESS: Check for exported actions JSON FIRST (before asking the founder anything).**
  1. Check `~/Downloads/actions-YYYY-MM-DD.json` (yesterday's date)
  2. Also check `q-system/output/actions-YYYY-MM-DD.json` (backup location)
  3. If found, parse it:
     - `"done"` items = founder confirmed they did it. Update state files (LinkedIn Tracker, Contacts DB, engagement log, lead signals). No need to ask.
     - `"skipped"` items = founder chose not to. No follow-up needed. Don't surface these again.
     - Cards MISSING from the export (present in morning log but not in actions JSON) = founder never opened the HTML or didn't click the button. Only ask about THESE cards.
  4. If no export file exists at all, fall back to the previous behavior: find the most recent morning log (glob `output/morning-log-*.json`, sort by date, take the latest that is NOT today). Read its `action_cards` for any with `founder_confirmed: false`. List them and ask: "Last session I drafted these for you. Which ones did you actually do?"
  For each confirmed (from JSON or verbal): update the card, then update Notion (LinkedIn Tracker, Contacts DB, etc.). List which state files were updated in `logged_to`.
  For each not done: carry forward by adding to TODAY's action cards via `log-step.py DATE add-card`.
  **Generate effort string for today's HTML:** From the actions data (JSON export or verbal), build a summary like "8 done, 3 skipped. 5 comments posted, 2 DMs sent, 1 debrief done." Store this in the morning log so Step 11 can read it and set the `effort` field in today's schedule JSON. If no actions data exists (first run or missed day), set effort to null.
  Also check `verification_queue` for unverified claims - re-verify any that are now stale (>48h).
  **Then:** Cross-reference recent calendar events against Notion Interactions DB. Any meeting with an external person that has no matching Interaction = missed debrief. Prompt founder and run `/q-debrief`.
  **Then:** Check recent debriefs in `my-project/progress.md` for practitioner/CISO conversations that have no corresponding follow-up Action in Notion Actions DB. If a debrief happened but no design partner conversion message was sent (no Action with Type = Follow-up Email and the person's name), flag it: "[Person] conversation was debriefed but no conversion message was sent. Want me to generate one now?"
  ```bash
  python3 q-system/.q-system/log-step.py DATE 0b_missed_debrief done "X cards confirmed, Y carried forward, Z debriefs found"
  ```
- **0b.5 - Loop escalation and auto-close:**
  Run the loop tracker to escalate all open loops and auto-close any that have evidence of completion.
  ```bash
  # Escalate all loops based on age
  python3 q-system/.q-system/loop-tracker.py escalate
  # Check stats
  python3 q-system/.q-system/loop-tracker.py stats
  # List any loops at level 2+ (need attention)
  python3 q-system/.q-system/loop-tracker.py list 2
  ```
  **Auto-close logic (run during Steps 1 and 3.8):**
  - Step 1 (Gmail): When scanning emails, cross-reference senders against open loops of type `email_sent` or `materials_sent`. If reply found: `python3 q-system/.q-system/loop-tracker.py close <loop_id> "email reply detected" "auto_gmail"`
  - Step 3.8 (DM check): When detecting DM replies, cross-reference against open `dm_sent` and `dp_offer_sent` loops. When detecting connection accepts, cross-reference against `connection_request_sent` loops. Close matches: `python3 q-system/.q-system/loop-tracker.py close <loop_id> "DM reply detected" "auto_step_3.8"`
  **Loop opening (run during Steps 5.85, 5.9b, 9, and /q-debrief):**
  Every outbound action that expects a response MUST open a loop:
  ```bash
  python3 q-system/.q-system/loop-tracker.py open <type> <target> <context> [notion_id] [card_id] [follow_up_text]
  ```
  Types: dm_sent, email_sent, materials_sent, comment_posted, action_created, debrief_next_step, dp_offer_sent, connection_request_sent, lead_sourced
  ```bash
  python3 q-system/.q-system/log-step.py DATE 0b.5_loop_escalation done "X open loops (L0:X L1:X L2:X L3:X)"
  ```
- **0c - Load canonical state + snapshot state checksums:**
  Read all canonical files to load current context into this session. This now includes any updates from Step 0b debriefs.
  **HARNESS: Snapshot state file checksums.** Read these key fields and record each:
  ```bash
  python3 q-system/.q-system/log-step.py DATE checksum-start last_calendar_sync "2026-03-13"
  python3 q-system/.q-system/log-step.py DATE checksum-start last_gmail_sync "2026-03-13"
  python3 q-system/.q-system/log-step.py DATE checksum-start dp_prospect_count "17"
  python3 q-system/.q-system/log-step.py DATE checksum-start dp_outreach_count "3"
  python3 q-system/.q-system/log-step.py DATE checksum-start decisions_rule_count "17"
  python3 q-system/.q-system/log-step.py DATE checksum-start last_publish_date "2026-03-10"
  python3 q-system/.q-system/log-step.py DATE 0c_load_canonical done "loaded, 6 checksums captured"
  ```
  Sources: `memory/morning-state.md` (sync dates), `my-project/relationships.md` (DP counts from Notion query), `canonical/decisions.md` (rule count), `memory/marketing-state.md` (publish date).
- **0d - Load voice skill:**
  > Log: `python3 q-system/.q-system/log-step.py DATE 0d_load_voice done "loaded"`
  Read `plugins/kipi-core/skills/founder-voice/references/voice-dna.md` and `plugins/kipi-core/skills/founder-voice/references/writing-samples.md`. ALL written output for the rest of the session (posts, comments, DMs, emails, outreach, replies) must pass through the voice skill rules. This is not optional.
- **0e - Load AUDHD executive function skill:**
  > Log: `python3 q-system/.q-system/log-step.py DATE 0e_load_audhd done "loaded"`
  Read `plugins/kipi-core/skills/audhd-executive-function/SKILL.md`. Check `my-project/founder-profile.md` for AUDHD preferences. This skill governs how ALL output is structured, especially the daily schedule HTML. Every action item must be copy-paste ready with inline text and a Copy button. No cross-references. No dashboards without actions. No scores without recovery drafts. The system decides what to do, the founder only executes. This is not optional. Every step that produces output for the founder must comply with the actionability rules (A1-A7) and pass the 10-point quality check before being shown.

- **0f - Server connectivity check (FAIL-FAST, RUNS FIRST before 0a-0e):** This is the VERY FIRST thing `/q-morning` does. Before checkpoint, before debrief detection, before loading skills. Test ALL 9 connections (Calendar, Gmail, Notion API, Chrome, Apify [X only], Reddit MCP, RSS feeds [Medium/Substack], VC Pipeline API, NotebookLM) using the exact tests defined in the "Fail-fast mode" section below. ALWAYS print the pass/fail table. If ANY critical server fails (Calendar, Gmail, Notion, Chrome), STOP the entire routine immediately. Apify and RSS failures are non-critical (Chrome fallback available). See "Fail-fast mode" for the full test table and output format.
- **0g - Monthly checks (1st of month only):** (1) Decision origin audit: count tags in decisions.md, flag if >60% rubber-stamped. (2) Review `memory/monthly/` files, promote proven patterns to canonical, delete invalidated ones. (3) Prediction calibration: analyze `memory/working/predictions.jsonl` for last 30 days, calculate accuracy, save to `memory/monthly/prediction-calibration-YYYY-MM.md`. (4) Outreach A/B analysis: group outcomes by style code, calculate reply rates per style, save to `memory/monthly/outreach-ab-YYYY-MM.md`.

- **0h - Context budget strategy:** The morning routine is split into two halves. If context is running low after Step 5.9b, auto-run `/q-handoff` and tell the founder: "Context is getting tight. Running handoff. Start a new session and run `/q-morning` again - it will pick up from the handoff note and skip to Step 11 (HTML generation)." The handoff note must include all data collected so far (calendar, actions, hitlist items, lead sourcing results) as structured data so the next session can build the JSON without re-running Steps 1-5.

**Context-saving rules (ENFORCED across all steps):**
- **Never hold raw scrape results (Chrome, Reddit MCP, RSS, Apify) in context.** Save to bus/ or `output/lead-gen/` files immediately. Read back only the qualified subset.
- **Never generate content for the wrong day.** Tuesday = TL post only. Friday = Medium only. Don't generate signals + TL + hot take + BTS all on the same day unless it's Monday.
- **Step 5.9 Phase 2: score in batches.** Read 10 results, score, discard sub-10 scores immediately. Don't hold all 50 raw results in context simultaneously.
- **Step 5.9b: cap at 10 engagement targets.** If 15 targets are eligible, pick the top 10 by priority. Fewer better comments > more rushed ones.
- **Meeting prep: only today's meetings get full prep.** This-week meetings get a one-line note. Next-week meetings get nothing.
- **Steps 6-7 (compliance/freshness): skip if context < 40%.** These are important but not critical. The HTML is the deliverable.

After Step 0, the session is fully initialized. The founder never needs to run `/q-begin`, `/q-end`, or `/q-checkpoint` separately.

**Step 1 — Parallel data pull (4 agents simultaneously):**
> **HARNESS:** After all 4 agents complete, log EACH as a separate step: `1_calendar`, `1_gmail`, `1_notion_actions`, `1_notion_pipeline`, `1_vc_pipeline`. Each gets its own status (done/failed/skipped) with result summary. If any agent fails, log it as failed with the error, but continue with the others (data pull is independent).

- **Calendar agent:** Pull Google Calendar events for the current week. Format as list with date, time, attendee, topic. **NEW EVENT DETECTION (B4):** Cross-ref attendee names against Notion Contacts DB. If a calendar event exists with a known prospect/VC/design partner AND no matching "scheduled call" entry in LinkedIn Tracker or Actions DB: auto-detect it as a newly scheduled meeting. Auto-advance relationship stage (if applicable), auto-create Meeting Prep action (Energy: Deep Focus, Time: 15 min, Priority: Today if meeting is today, This Week otherwise). The founder NEVER needs to say "scheduled a call with [name]."
- **Email agent:** Search Gmail for last 48 hours (inbox AND sent). Cross-reference sender names against Notion Contacts DB and Interactions DB. Flag emails from known contacts that have no matching interaction logged. **EMAIL CONVERSATION DETECTION (C4):** Also check Gmail sent folder for outbound emails to prospects in the last 48h. For each sent email to a known Contact: check if there's an inbound reply in the inbox. If reply found: auto-update Contact (Last Contact = today), flag as "email reply received" for temperature scoring. If no reply and email was sent 7+ days ago: note as unreturned email for channel death tracking. This removes the need for the founder to report "X replied to my email."
  **LOOP AUTO-CLOSE (Gmail):** After processing emails, read `output/open-loops.json`. For each open loop of type `email_sent` or `materials_sent`, check if the loop's target name appears as a sender in the inbox results. If reply found:
  ```bash
  python3 q-system/.q-system/loop-tracker.py close <loop_id> "email reply detected in Gmail" "auto_gmail"
  ```
- **Notion agent:** Pull Actions DB for overdue/due-today items (filter by Due date and Priority). Pull Investor Pipeline for upcoming follow-ups. **STALE ACTION CLEANUP (D5):** For any Actions with Due date > 7 days past AND Priority != "Someday": auto-move Priority to "Someday". Surface count quietly in briefing: "[X] stale actions moved to Someday" (no guilt, no list of what was missed). The founder can review Someday items when they have capacity. This prevents open-loop accumulation. **NOTE:** Actions DB has no "Status" property - use Priority (Today/This Week/Next Week/Someday) for filtering. See KI-3 in preflight.md.
- **VC Pipeline agent:** Fetch `http://localhost:5050/api/pipeline` to pull the full VC Pipeline Manager data (66+ contacts with warm intro paths, statuses, tiers). This data is used in Steps 1.5 and 3.5 for warm intro matching.

**Step 1.1 — (Moved to Step 0b)** Missed debrief detection now runs in Step 0 before data pull.

**Step 1.5 — Warm intro path matching (VC + Design Partner):**

Uses VC Pipeline data from Step 1 + Notion Contacts DB to find warm intro paths for new prospects.

- **For new DP prospects** (added since last morning check): Cross-reference each prospect against:
  1. **VC Pipeline warm paths** (`http://localhost:5050/api/pipeline`): 20+ contacts have mapped warm intro paths with named connectors (e.g., "Via Guy Rosen (Meta CISO)", "Via Prabhath Karanth", "Via Limor Elbaz (1st degree, CONFIRMED)"). Check if any VC pipeline connector ALSO knows the DP prospect (same company, same industry, mutual connections).
  2. **Notion Contacts DB** (82+ contacts): Search for existing contacts at the prospect's company, in their industry, or with overlapping LinkedIn networks. Anyone with Type = Connector, Advisor, or Operational who works in the same space.
  3. **Chrome mutual connections** (if visible on profile page): Navigate to the prospect's LinkedIn profile via Chrome. Note mutual connection count with founder. Flag any mutuals who are already in Notion Contacts DB or VC Pipeline.
- **Output appended to morning briefing:**
  ```
  WARM INTRO OPPORTUNITIES
  [Prospect Name] -> [Connector Name] ([relationship]) -> Suggested ask: [one-line]
  [Prospect Name] -> No warm path found. Cold outreach recommended.
  ```
- **Auto-update Notion:** For prospects where a warm path is found, update the Contact record with the intro path. Create an Action: "Ask [Connector] for intro to [Prospect]" (Energy: People, Time: 5 min, Priority: This Week).
- **Rule:** Warm intro always beats cold outreach. If a warm path exists, do NOT send a cold DM. Route through the connector instead.

**Step 2 — Meeting prep (TODAY's meetings get full prep, this-week gets one-line note):**
> **HARNESS:** Log as `2_meeting_prep` when done. Result = count of meetings prepped.

**CONTEXT-SAVING:** Full research + Chrome + NotebookLM + VC prep brief = only for TODAY's meetings. Meetings later this week get a one-line entry in the FYI section ("Wed: Call with X, prep needed tomorrow"). Meetings next week get nothing. This prevents 3-person meeting prep from consuming 30% of context.
- **Chrome browser** (`mcp__claude-in-chrome__*`): Navigate to attendee's LinkedIn profile. Read their role, company, headline, summary, recent posts, and engagement. Process attendees sequentially (one browser tab). Chrome is the primary tool for all LinkedIn profile/post data.
- **Notion CRM**: Cross-reference attendee name against Contacts + Interactions DB — pull all past conversations, what was discussed, open items, last follow-up.
- **NotebookLM** (`mcp__notebooklm__*`): For high-priority meetings (VCs, design partners), create or update a research notebook per person/company. Enables pre-call Q&A like "what does this person care about?"
- **VC call prep brief (for VC/investor meetings only):**
  - Use the `sales-enablement` skill with the VC call prep template (`references/vc-call-prep-template.md`)
  - Research: the person, the fund, portfolio companies (especially security/compliance/infrastructure), venture partners, recent investments, their stated thesis language
  - Every brief must have specific hooks showing why THIS fund specifically matters for {{YOUR_PRODUCT}} (portfolio company names, venture partner backgrounds, thesis alignment)
  - The goal: make the founder feel like they chose this VC on purpose, not that they're running a spray-and-pray process
  - Save to `output/meeting-prep/[fund]-[person]-YYYY-MM-DD.md`
- **Fundability signal check (also for VC meetings):**
  - Review `canonical/talk-tracks.md` "Fundability Framework" section
  - Prep stage anchoring opener for this specific investor
  - Prep dominant risk framing with evidence
  - Prep causal "why now" (detection eng discipline + regulation + re-breach data)
  - Prep self-audit answers (what's biggest risk, what changed in 60 days, smallest experiment, metric to raise faster)
  - Check: does our prep lead with multi-output proof, not detection-only?
  - Check: are milestones framed as risk-removal, not activities?
- **Output per meeting:**
  ```
  [Name] - [Role] at [Company]
  LinkedIn: [key info - focus areas, recent posts, mutual connections]
  History: [last interaction, what was discussed, what you owe them]
  Prep: [suggested talking points based on their interests + our positioning]
  Fundability signals (VC only): [stage anchor, risk framing, why now angle, proof points to lead with]
  ```

**Step 2.5 — X activity review:**
- **Apify** (`mcp__apify__*`): Use `apidojo~tweet-scraper` actor to pull {{YOUR_X_HANDLE}} recent posts with engagement metrics (impressions, likes, retweets, replies, quotes). Also scrape recent posts from target accounts for QT/reply targets. Apify is used ONLY for X/Twitter in this system.
- **Chrome browser** (`mcp__claude-in-chrome__*`): Use for checking notifications (new followers, DMs), posting replies, and as fallback if Apify fails.
- **Engagement opportunities:** Flag accounts that engaged with your posts for DM follow-up (warm leads)
- **Reply to comments:** If any posts from yesterday have replies, draft quick responses (first 30 min engagement matters)
- **Weekly metrics (Mondays only):** Pull from Apify/Chrome scrape data: impressions, engagement rate, follower count, top/bottom 3 posts. Compare to prior week. Update `canonical/content-intelligence.md` X baselines.
- **Output:**
  ```
  X ACTIVITY
  New followers: [X]
  Replies to respond to: [list]
  DM opportunities (people who engaged): [list]
  QT/reply targets today: [3-5 posts from security Twitter]

  X METRICS (Mondays only):
  Followers: [X] (+/- vs last week)
  Top post: [text] - [impressions] impressions, [engagement]
  Engagement rate: [X]%
  ```

**Step 3 — LinkedIn activity review:**
> **HARNESS:** Log as `3_linkedin_activity` when done. Result = re-engage count + new opportunities.

- **Chrome browser** (`mcp__claude-in-chrome__*`): Navigate to founder's LinkedIn profile to read recent posts with engagement data (impressions, likes, comments, reposts). Also check Comments tab (`/recent-activity/comments/`) for comment-on-comment engagement. Use Chrome for all interactive actions (posting comments, replying). Chrome is the primary tool for ALL LinkedIn data.
- **Posts analysis:** Check own posts for impressions, comments, reposts since last check. Feed engagement data into `canonical/content-intelligence.md`.
- **Market intelligence from replies:** Evaluate replies and comments on founder's posts for canonical value. Someone replying "we have this exact problem, we use X today" or "I tried building this internally and it failed because..." is market signal. Apply the 6 market intelligence lenses (problem language, category signal, objection preview, competitive intel, buyer process, narrative check). Log to `canonical/market-intelligence.md` if new signal.
- **Re-engagement opportunities:** For each comment with new replies or high traction:
  - Should founder reply to a reply? (continue conversation = relationship building)
  - Did a target person (VC/CISO/Design Partner) engage? Flag for DM follow-up.
  - Did the comment create an opening for a connection request?
- **LOOP AUTO-CLOSE (LinkedIn comments):** Cross-reference comment replies against open loops of type `comment_posted`. If someone replied to a comment the founder posted:
  ```bash
  python3 q-system/.q-system/loop-tracker.py close <loop_id> "reply on comment detected" "auto_step_3"
  ```
  **IMPORTANT:** Step 3 MUST check the Comments tab (`/recent-activity/comments/`), not just the Posts tab. The step result logged to the morning log must explicitly say "comments tab checked." If only Posts tab was checked, the step is INCOMPLETE per the Deliverables Checklist.
- **New post opportunities:** Scan founder's feed for trending posts from target contacts that haven't been engaged yet
- **Cross-reference Notion:** Check LinkedIn Tracker DB for items with Follow-up Date = today or overdue
- **Output:**
  ```
  🔄 RE-ENGAGE (comments with new activity)
  1. [Post author] — [topic] — [your comment got X replies]
     → [Suggested reply or action]

  🆕 NEW POST OPPORTUNITIES
  1. [Target name] posted about [topic] — [suggested angle]

  ⏰ FOLLOW-UPS DUE
  1. [Name] — [original engagement] — due [date]
  ```

**Step 3.2 - Post-publish reconciliation (LinkedIn):**

Detects content published directly (not through Q) and updates tracking to match reality.

- **Compare Chrome LinkedIn data (from Step 3) against Content Pipeline DB:**
  - Pull all posts from the Chrome LinkedIn scrape (Step 3 already has this data)
  - Pull all entries from Content Pipeline DB with Status = Drafted or Reviewed (these are Q-generated drafts)
  - For each LinkedIn post from the last 7 days:
    1. **Fuzzy match** the post text against drafted content (check first 50 chars, hashtags, or key phrases)
    2. If a match is found AND the Content Pipeline entry is NOT yet marked Published:
       - Auto-update Content Pipeline DB: Status -> Published, Published Date -> post date from LinkedIn
       - Update `memory/marketing-state.md` Publish Log
       - Update Content Cadence counts for the week
       - Log: "Auto-detected publish: [post summary] on [date]"
    3. If a LinkedIn post has NO match in Content Pipeline DB:
       - This was published outside Q (direct post, not from a draft)
       - Create a Content Pipeline DB entry retroactively (Type: LinkedIn Post, Status: Published, Published Date: post date, Notes: "Published directly, not through Q")
       - Log: "Direct publish detected: [post summary] on [date]"
- **Also check X/Twitter** (from Step 2.5 Apify/Chrome data): Same reconciliation for tweets. Match against Content Pipeline DB entries with Type = X Post.
- **Output appended to morning briefing (only if changes found):**
  ```
  PUBLISH RECONCILIATION
  Auto-detected: [X] posts published from Q drafts (Pipeline updated)
  Direct publishes: [X] posts published outside Q (Pipeline entries created)
  Content cadence adjusted: [updated counts]
  ```
- **Rules:**
  - This runs silently if everything matches. Only surface output if discrepancies are found.
  - Fuzzy matching uses first 50 chars + hashtag overlap. If uncertain, err on the side of creating a new entry (duplicates are easy to merge, missed entries cause drift).
  - This step MUST run before Step 4 (content generation) so the cadence check has accurate counts.

**Step 3.5 - Design Partner pipeline check:**
> **HARNESS:** Log as `3.5_dp_pipeline` when done. Result = counts by DP status + auto-close count.

- **Pull Contacts DB** for Type = Design Partner. Count by DP Status (Prospect, Outreach Sent, Demo Done, etc.)
- **Flag prospects needing outreach:** DP Status = Prospect with no Follow-up Action or Follow-up Action = empty
- **Flag stale outreach:** DP Status = Outreach Sent with Last Contact > 7 days ago and no response
- **Auto-close dead loops (ADHD loop hygiene):** For any contact with 3+ logged touches (across LinkedIn Tracker + Interactions DB) AND no response (check DMs in Step 3.8 + Interactions DB + LinkedIn Tracker for any inbound from them) AND last touch > 14 days ago: automatically update DP Status to "Passed", add note "Auto-closed: 3 touches, no response." Do NOT surface these as action items. Do NOT ask the founder to decide. Just close them and report the count. This removes open loops without requiring a decision. **Important:** Step 3.8 (DM check) must run BEFORE auto-close to catch any DM responses that would keep a contact alive.
- **New prospect sourcing:** If total active prospects in pipeline < 12 (lowered from 15 to keep pipeline clean and manageable), flag "Pipeline light - you could run Monday sourcing if you have energy for it"
- **Personalized outreach queue:** For any Prospect contacts with Follow-up Action containing "personalized message ready", surface them as ready-to-send
- **Output appended to morning briefing:**
  ```
  DESIGN PARTNER PIPELINE
  Prospects: [X] | Outreach Sent: [X] | Demo Done: [X] | Active: [X]
  Auto-closed this check: [X contacts] (3 touches, no response - moved to Passed)
  Ready to send: [list contacts with personalized messages prepared]
  Need research + personalization: [list Prospect contacts without messages]
  Pipeline health: [OK if 12+ active / LIGHT if <12 - "you could source more if you have energy"]
  ```
- **If prospects need personalization:** Offer to run `/q-engage dp-outreach` for those contacts

**Step 3.7 — Content intelligence pull (weekly, Mondays):**
- **Scrape own content** across all platforms using Chrome (LinkedIn), Reddit MCP, Apify (X only), and RSS feeds (Medium, Substack):
  - LinkedIn: Navigate to founder's profile via Chrome, read all posts from last 7 days with engagement metrics
  - X: Use Apify `apidojo~tweet-scraper` on {{YOUR_X_HANDLE}} to pull all tweets from last 7 days with impressions, likes, retweets, replies
  - Medium: Pass 1: `WebFetch(url="https://medium.com/feed/@{{YOUR_MEDIUM_HANDLE}}", prompt="Extract all articles: title, URL, author, date, content text. Return as numbered list.")`. Pass 2: Navigate to each article via Chrome to get claps, responses, read ratio (RSS doesn't have engagement metrics).
  - Reddit: Use Reddit MCP `mcp__reddit__get_user_posts` with `username={{YOUR_REDDIT_USERNAME}}`, `limit=20`. Returns posts with title, score (upvotes), comments, subreddit, full content. No two-pass needed.
  - Substack: `WebFetch(url="https://{{YOUR_SUBSTACK}}.substack.com/feed", prompt="Extract all posts: title, URL, date, content text. Return as numbered list.")`. Open rate requires Substack dashboard via Chrome.
- **Analyze patterns:**
  - Rank all posts by engagement rate (not raw numbers)
  - Identify top 3 and bottom 3 performers
  - Extract common language, format, and topic patterns from top performers
  - Extract patterns from underperformers (what to avoid)
  - Compare performance by theme (map each post to one of 8 content themes)
  - Check optimal posting times (when did high performers go out?)
- **Update `canonical/content-intelligence.md`:**
  - Refresh Performance Baselines tables
  - Add new entries to "What Works" and "What Doesn't Work"
  - Update Theme Performance table
  - Add Weekly Intel Log entry
- **Output appended to morning briefing (Mondays only):**
  ```
  CONTENT INTELLIGENCE (last 7 days)
  Top performer: [platform] - [post summary] - [engagement rate]
  Worst performer: [platform] - [post summary] - [engagement rate]
  Pattern spotted: [what worked / what didn't]
  Language to reuse: [specific phrases from top posts]
  Language to avoid: [specific phrases from bottom posts]
  Theme ranking: [best to worst theme this week]
  Recommendation: [one specific adjustment for this week's content]
  ```

**Step 4: Signals content + social posts (DAY-SPECIFIC, do NOT generate everything every day):**

> **HARNESS: Action cards.** For every post/content draft generated in this step:
> ```bash
> python3 q-system/.q-system/log-step.py DATE add-card P1 linkedin_publish "Signals post" "Three critical security..." ""
> python3 q-system/.q-system/log-step.py DATE add-card P2 x_publish "X signals" "SolarWinds WHD has..." ""
> ```
> Never update Content Pipeline DB or marketing-state.md publish log until `founder_confirmed: true`.
> ```bash
> python3 q-system/.q-system/log-step.py DATE 4_signals done "3 posts drafted, 3 action cards"
> ```

**CONTEXT-SAVING: Only generate the content type assigned to today.**
- **Mon/Wed/Fri:** Signals post (LinkedIn + X) + X hot take + X BTS
- **Tue/Thu:** Thought leadership post (LinkedIn + X). NO signals post.
- **Weekly (Wednesdays): Kipi System promotion post.** One building-in-public post about the open source repo (https://github.com/assafkip/kipi-system). Follows a 4-week rotation:
  - Week 1: r/ClaudeAI post (architecture, Claude Code build, screenshots). Follow `marketing/templates/reddit-post.md`.
  - Week 2: r/ADHD post (executive function, no shame language, how it helps). Follow `marketing/templates/reddit-post.md`.
  - Week 3: LinkedIn series (5 posts Mon-Fri, each showing one thing the system did that day)
  - Week 4: X thread (full walkthrough, 10-15 tweets, repo link at end)
  - Track which week we're on in `memory/morning-state.md` field `kipi_promo_week` (1-4, auto-increment).
  - Every post must include a screenshot or screen recording. No text-only posts for the repo.
  - Log as `4_kipi_promo`. Generate the post copy-paste ready in the HTML.
- **Fri (additional):** Medium article draft
- **Never generate all content types on the same day.** This is the single biggest context waster in Step 4.

- **Before generating any content:** Read `canonical/content-intelligence.md` for current patterns. Use high-performing language/formats. Avoid low-performing patterns. Score each draft against the Content Scoring Model before finalizing.
- **Templates:** `marketing/templates/linkedin-signals.md` (LinkedIn format), `marketing/templates/x-signals.md` (X format). Follow their Pre-Generation Steps, Rules, and Imagery sections.
- **Fetch {{YOUR_DOMAIN}}/signals (Mon/Wed/Fri only):** Use `WebFetch` to pull the latest signals from the signals page
- **Pick 2-4 top signals** that are: (a) breaking news, high severity, actively exploited, or big-name brands, (b) trending or viral potential (data leaks, source code dumps, major CVEs), (c) interesting to security and fraud practitioners
- **Generate LinkedIn post:** Breaking news roundup format. Lead with the most attention-grabbing signal. List 2-4 signals with key facts (numbers, affected products, what happened). End with link to {{YOUR_DOMAIN}}/signals and total signals analyzed. Goal: drive traffic to the signals page, NOT thought leadership or {{YOUR_PRODUCT}} positioning.
- **Generate X signals post:** 1-2 sentences or a thread hook (280 char max for the lead). Punchier, headline-style. End with link to {{YOUR_DOMAIN}}/signals.
- **Generate X hot take:** Scan security news (from signals + trending X topics) for something to react to. One tweet, no thread. Sharp, opinionated, practitioner voice. Connect to institutional memory, learning failure, or nervous system framing without naming {{YOUR_PRODUCT}}. Examples:
  - Vendor announces "AI-powered detection" -> "You can't prompt-engineer a nervous system."
  - Major breach -> Connect to institutional memory failure
  - VC posts security thesis -> Engage with practitioner perspective
  - Industry report -> Contrarian take on what the data actually means
- **Output:**
  ```
  SIGNALS POST (from {{YOUR_DOMAIN}}/signals)

  Signal: [title / CVE / threat actor]
  Why it matters: [one line]

  LINKEDIN POST:
  [draft post, 3-5 sentences]

  X SIGNALS POST:
  [draft post, 1-2 sentences, 280 char max lead]

  X HOT TAKE:
  [1 tweet, opinionated, practitioner voice]
  Topic: [what triggered it]
  ```
- **Rules:** No "AI-powered" or "cutting-edge." No {{YOUR_PRODUCT}} pitch or positioning angle. This is a BREAKING NEWS post. Founder sharing signals to drive traffic to {{YOUR_DOMAIN}}/signals, not thought leadership. Write like a practitioner sharing news, not a vendor framing narratives. NEVER use emdashes in posts. Hot takes can reference the nervous system metaphor but should NOT name {{YOUR_PRODUCT}} directly. Hot takes should aim for under 100 characters when possible.
- **Generate X behind-the-scenes post (Mon/Wed/Fri):** Building-in-public content. One tweet about the founder journey, a decision made, something learned from a CISO conversation (anonymized), or a challenge being faced. Vulnerable, honest, specific. Use Pratfall Effect - showing imperfection makes you more relatable.
- **Generate X visual post idea (Wed):** Suggest a visual to create - screenshot of demo output, simple diagram, breach timeline. Founder creates the visual, Claude drafts the caption. Images stop the scroll; text delivers value.
- **Generate Gamma visual for signals post:** Call `mcp__gamma__generate_gamma` with format "social", inputText = top signal headline + key stat (e.g., "3.4M patients exposed - Cognizant TriZetto breach"). Use brand kit colors (dark bg, indigo accent). Save Gamma URL in the signals post file. This image gets posted alongside the LinkedIn and X signals posts.
- **ALWAYS save to file:** Write the signal post to `output/signals-post-YYYY-MM-DD.md` with LinkedIn draft, X draft, signal source, Gamma visual URL, and checkbox status. This is the canonical copy. Daily Posts page in Notion links to it.

**Step 4.1 — Value-first intel routing (daily, high priority):**

Send today's signals directly to people who would be AFFECTED by them. Not prospects, not a pitch. People who'd get real value from knowing about this breach/CVE/advisory before it hits their inbox from a vendor. This is the best relationship-building move in the system.

- **WHO GETS THESE:**
  - **ALL contacts in Notion Contacts DB** (any Type, any Status) who match by industry, tools, or role. Not limited to DP prospects or VCs.
  - **Email contacts** from Gmail/relationships who aren't in Notion but would be affected. CISOs, security leaders, practitioners in your network.
  - The test: "Would this person's Tuesday change if they saw this signal right now?" If yes, send it.

- **MATCHING LOGIC (signal -> person):**
  - **By vendor/tool affected:** Signal mentions SailPoint vulnerability -> send to everyone you know who runs SailPoint. Signal mentions CrowdStrike issue -> send to CrowdStrike users in your network.
  - **By industry:** Healthcare breach -> healthcare security contacts. Financial sector advisory -> FinServ CISOs.
  - **By threat actor/campaign:** Nation-state campaign targeting defense -> government/defense contacts.
  - **By role relevance:** New TTP/MITRE update -> detection engineers. Compliance deadline -> GRC contacts. Board-level risk -> CISOs.
  - Pull industry/company/tools from Notion Contact records (Company, Notes fields) and from LinkedIn profile data if available.

- **LINK TO SPECIFIC REPORT (mandatory):**
  - Every value-drop DM/email MUST link to the specific report URL on the signals page, not the homepage.
  - Format: `https://{{YOUR_DOMAIN}}/signals/[report-slug]?utm_source=[source]&utm_medium=[medium]&utm_campaign=value-intel&utm_content=[person-slug]`
  - Fetch the signals page, identify the individual report URLs, use those in messages.
  - If no individual URL exists for a signal, link to the signals page with an anchor or the closest match.

- **MESSAGE FORMAT (copy-paste ready, run through founder-voice skill):**
  - LinkedIn DM and email versions for each.
  - Reference the specific signal and WHY it matters to THEM.
  - Link to the specific report.
  - No pitch. No {{YOUR_PRODUCT}} mention. Pure intel sharing.
  ```
  INTEL DROPS TO SEND TODAY

  SIGNAL: [breach/CVE/advisory title]
  Report: [specific URL on {{YOUR_DOMAIN}}/signals/report-slug]

  SEND TO (LinkedIn DM):
  1. [Name] ([Company], [Role]) - why: [they run the affected tool / in the affected industry]
     💬 "[copy-paste DM with link to specific report]"
     ⏱️ 2 min | Quick Win

  2. [Name] ([Company], [Role]) - why: [reason]
     💬 "[copy-paste DM]"
     ⏱️ 2 min | Quick Win

  SEND TO (Email):
  1. [Name] ([email]) - why: [reason]
     💬 "[copy-paste email with link to specific report]"
     ⏱️ 2 min | Quick Win
  ```

- **VOLUME:** No daily cap on sends. If 8 people in your network run SailPoint and there's a SailPoint advisory, send to all 8. The cap is relevance, not a number. But still max 1 value drop per person per week.

- **UTM link generation (MANDATORY for all outreach):**
  - Every link sent MUST include UTM parameters for tracking
  - Format: `https://{{YOUR_DOMAIN}}/signals/[report-slug]?utm_source=[source]&utm_medium=[medium]&utm_campaign=value-intel&utm_content=[person-slug]`
  - **utm_source:** `linkedin`, `email`, `twitter`
  - **utm_medium:** `dm`, `email`, `comment`
  - **utm_campaign:** `value-intel` (replaces old `value-drop` - this is intel sharing, not dropping)
  - **utm_content:** person slug (lowercase, hyphenated name)
  - Log the UTM link in Notion LinkedIn Tracker entry so we know which link was sent to whom

- **RULES:**
  - NO {{YOUR_PRODUCT}} pitch. Zero. This is a practitioner sharing intel with their network.
  - Max 1 per person per week (don't spam)
  - The signal must be genuinely relevant to their specific situation. "Would their Tuesday change?" If no, don't send.
  - All copy goes through founder-voice skill before output. Casual, direct, helpful.
  - Log to Notion LinkedIn Tracker DB after sending (Type: Outreach DM, note: "Intel drop - [signal topic]", UTM link)
  - After 3 intel drops with no response AND no link clicks in GA, stop. They're not reading them.
  - **Email sign-off:** just "Assaf" (no Best/Cheers/Regards)

- **Create Actions** for each intel drop: (Energy: Quick Win, Time: 2 min, Priority: Today, Type: LinkedIn or Follow-up Email)

**Step 4 (continued) — Marketing content generation:**
- **If Tuesday or Thursday:** Also generate thought leadership posts from the editorial calendar theme:
  - Read `marketing/editorial-calendar.md` for this week's assigned theme + topic
  - Read `marketing/content-themes.md` for theme's canonical sources
  - Follow `marketing/templates/linkedin-thought-leadership.md` template for LinkedIn
  - Follow `marketing/templates/x-thought-leadership.md` template for X (3-5 tweet thread, sharper/more opinionated than LinkedIn, each tweet stands alone)
  - Query NotebookLM if theme benefits from research grounding (see content-themes.md per-theme guidance)
  - **Generate LinkedIn carousel via Gamma:** Call `mcp__gamma__generate_gamma` with format "presentation", inputText = 3-5 key insights from the TL post (one per slide), textMode "condense". This becomes a carousel PDF the founder uploads alongside the text post. Save Gamma URL + PDF export link.
  - **Generate X social card via Gamma:** Call `mcp__gamma__generate_gamma` with format "social", inputText = the sharpest line from the TL post. Single image card for the lead tweet.
  - Save LinkedIn to `output/marketing/linkedin/linkedin-tl-YYYY-MM-DD.md` (include Gamma carousel URL + PDF link)
  - Save X thread to `output/marketing/x/x-tl-YYYY-MM-DD.md` (include Gamma social card URL)
  - Create Content Pipeline DB entry (Type: LinkedIn Post, Status: Drafted, Theme: [number])
- **If Friday:** Also generate a Medium article draft from this week's assigned topic:
  - Read `marketing/editorial-calendar.md` for Medium topic
  - Follow `marketing/templates/medium-article.md` template (multiple NotebookLM queries)
  - **Generate Medium header image via Gamma:** Call `mcp__gamma__generate_gamma` with format "social", inputText = article title + key stat or framing question. Save Gamma URL.
  - **Generate sharing card via Gamma:** Call `mcp__gamma__generate_gamma` with format "social", inputText = article title + one-line summary. For LinkedIn/X cross-promotion when article publishes.
  - Save to `output/marketing/medium/medium-YYYY-MM-DD-[slug].md` (include Gamma header URL + sharing card URL)
  - Create Content Pipeline DB entry (Type: Medium Article, Status: Drafted, Scheduled: Sunday)
- **If Saturday or Sunday:** Also generate a Substack newsletter from this week's assigned topic:
  - Read `marketing/editorial-calendar.md` for Substack topic
  - Follow `marketing/templates/substack-newsletter.md` template
  - Can repurpose/expand the Medium article with added commentary, or be original content
  - **Generate newsletter header via Gamma:** Call `mcp__gamma__generate_gamma` with format "social", inputText = newsletter title + key insight.
  - Save to `output/marketing/substack/substack-YYYY-MM-DD-[slug].md` (include Gamma header URL)
  - Create Content Pipeline DB entry (Type: Substack Newsletter, Status: Drafted, Scheduled: Sunday)

**Step 4.5 — Marketing health check:**
- **Asset freshness:** Read `memory/marketing-state.md` Asset Freshness table. For each asset, check if its source files have been modified since last refresh date. Flag any stale assets.
- **Gamma deck freshness:** Check Gamma Deck Tracker in marketing-state.md. If canonical files changed since deck generation, flag deck as "Needs Review."
- **Cadence check:** Read marketing-state.md Content Cadence table. Check progress against weekly targets:
  - Signals posts: on track? (should have one per weekday so far)
  - Thought leadership: on track? (Tue + Thu)
  - Medium: on track? (draft by Fri, publish by Sun)
- **Stale drafts:** Check Content Pipeline DB for items with Status = Drafted and age > 2 days. Flag for review.
- **Output appended to morning briefing:**
  ```
  📣 MARKETING HEALTH
  Assets: [X current / Y stale — list stale items]
  Gamma decks: [X current / Y need review]
  This week: [X/Y signals] [X/2 TL posts] [Medium: status]
  Stale drafts: [list or "None"]
  ```

**Step 5 — Weekly site metrics (MONDAYS ONLY — skip other days):**
- **Chrome browser** (`mcp__claude-in-chrome__*`): Navigate to Google Analytics (analytics.google.com, authuser=2, property a385692819p526076376)
- **Pull last 7 days:** Active users, sessions, new users, avg engagement time
- **Compare to prior 7 days:** Up/down/flat for each metric
- **Check by channel:** Direct vs Organic Social vs Organic Search vs Referral — is social growing?
- **Check landing pages:** /signals engagement time (benchmark: 21s), /demo active users, homepage bounce
- **Check key events** (once configured): demo_started, signals_engaged, suggestion_submitted counts
- **Flag anomalies:** Bot traffic spikes (Russia/other non-ICP countries), sudden drops, engagement time changes
- **Output:**
  ```
  📊 SITE METRICS (week of [date])

  Users: [X] ([+/-X] vs prior week)
  Sessions: [X] ([+/-X])
  New users: [X] ([+/-X])
  Avg engagement: [Xs] ([+/-Xs])

  CHANNELS:
  Direct: [X] | Social: [X] | Search: [X] | Referral: [X]

  TOP PAGES:
  /signals: [Xs] avg engagement, [X] sessions
  /demo: [X] active users
  /: [Xs] avg engagement

  KEY EVENTS: [counts or "not yet configured"]

  ⚠️ ANOMALIES: [bot traffic, drops, etc. — or "Clean"]
  ```
- **Benchmark targets** (set Feb 28 baseline): 55 MAU, 80 sessions, 14s avg engagement, 6 organic social sessions. Track progress weekly.

**Step 5.5 — Prospect engagement tracking (Mondays, after site metrics):**
- **Pull UTM data from Google Analytics:** In Chrome, navigate to GA4 > Reports > Acquisition > Traffic acquisition. Filter by utm_campaign containing `value-intel`, `value-drop`, `cold-outreach`, `follow-up`, `warm-intro`, `demo-share`. Group by utm_content (which is the person slug).
- **Cross-reference with Notion Contacts DB:** For each prospect slug that appears in GA:
  - They clicked. Update their Notion Contact record: add "Link clicked [date] - [page] via [campaign]" to notes or a dedicated field.
  - If they visited `/demo` and spent >30 seconds, flag as HOT lead in morning briefing.
  - If they visited `/signals` multiple times, flag as engaged.
- **Identify cold prospects:** Pull all contacts who were sent UTM-tagged links (from LinkedIn Tracker DB entries) but whose slug NEVER appears in GA utm_content data. These people never clicked.
- **Output appended to morning briefing (Mondays):**
  ```
  PROSPECT ENGAGEMENT (from UTM tracking)

  CLICKED (last 7 days):
  [Name] - visited /demo (2 min engagement) via cold-outreach DM - HOT
  [Name] - visited /signals via value-drop - engaged

  NEVER CLICKED (sent link, no visit):
  [Name] - sent demo link [date], no click after [X] days
  [Name] - sent 2 value drops, zero clicks

  RECOMMENDATION:
  [Name]: escalate - they're looking at the demo, send a follow-up
  [Name]: deprioritize - 2 links sent, zero engagement
  ```
- **Auto-update Notion:** Add engagement status to Contact records. Contacts who clicked get follow-up Actions created (Energy: Quick Win, Time: 5 min). Contacts who never clicked after 2+ sends get flagged for deprioritization (NOT auto-closed, just flagged - the founder decides on these since lack of click doesn't mean lack of interest, they might have seen it another way).

**Step 5.8 — Prospect engagement scoring (daily, runs after all data is collected):**
> **HARNESS:** Log as `5.8_temperature_scoring`. Result = hot/warm/cool/cold counts.

Stitches together ALL engagement signals from today's morning routine into one score per active prospect. No manual tracking needed.

- **Pull all active prospects** from Notion Contacts DB (Type = Design Partner or VC, Status not Passed/Declined)
- **Collect engagement signals per prospect from today's data:**

  | Signal | Points | Source |
  |--------|--------|--------|
  | Responded to DM | +5 | Step 3.8 (DM check) |
  | Replied to email | +5 | Step 1 (Gmail check) |
  | Commented on your LinkedIn post | +4 | Step 3 (LinkedIn activity) |
  | Liked/reposted your post | +2 | Step 3 (LinkedIn activity) |
  | Clicked UTM link to /demo | +4 | Step 5.5 (GA, Mondays) or carry forward from last Monday |
  | Clicked UTM link to /signals | +2 | Step 5.5 (GA, Mondays) or carry forward |
  | Accepted connection request | +2 | Step 3.8 (DM check) |
  | Viewed your LinkedIn profile | +1 | Step 3 (if visible in "Who viewed your profile") |
  | Posted about {{YOUR_PRODUCT}}-shaped problem | +3 | Step 5.9 (problem-language search) |
  | You sent outreach, no response | -1 per touch | Step 3.5 (pipeline check) |
  | No activity in 14+ days | -3 | Step 3.5 (last contact date) |

- **Calculate rolling engagement score** (last 14 days, decays over time):
  - **Hot (8+):** Multiple signals, actively engaging. Ready for next step (demo call, deeper conversation).
  - **Warm (4-7):** Some engagement, keep nurturing. Value drops and comments.
  - **Cool (1-3):** Minimal engagement. One more touch, then reassess.
  - **Cold (0 or negative):** No engagement despite outreach. Auto-close candidate (RULE-016).

- **Store score in Notion Contacts DB:** Update a "Engagement Score" or notes field with current score + trend arrow (up/down/flat vs last check). This persists across sessions.

- **ENFORCE lead lifecycle rules** (from `canonical/lead-lifecycle-rules.md`):
  - **Channel death check:** For each prospect, count unreturned touches per channel. 3 emails with no reply = email is dead. 3 DMs with no reply = DM is dead. BLOCK any new draft on a dead channel. Suggest channel switch instead.
  - **Auto-park check:** 3 touches across 2+ channels + 14 days no response = move to Parked. Remove from active hitlist. No more outreach until a trigger fires.
  - **High-value gate:** VC partners and CISOs with 3+ unreturned emails get NO new email drafts. Ambient engagement (LinkedIn comments, signals posts they'll see) or warm intros only.
  - **Re-engagement cap:** Parked contacts cannot be re-engaged for minimum 60 days unless a trigger fires (they engage with content, breach at their company, event encounter, warm intro materializes, genuinely new milestone from you).
  - **Trigger watch:** Parked contacts who engage with your content (like a post, visit site) get surfaced as re-engagement opportunities with one-touch draft.

- **Output in morning briefing (replaces scattered engagement data):**
  ```
  🌡️ PROSPECT TEMPERATURE (from Step 5.8)

  🔥 HOT (act today):
  [Name] (score: 9, ↑) [Stage: Conversation] [DP: Outreach Sent] - clicked demo + commented on your post + accepted connect
  → Suggested action: send follow-up DM, they're actively interested

  🟡 WARM (keep nurturing):
  [Name] (score: 5, →) [Stage: First DM] [DP: Outreach Sent] - clicked signals link, no DM response yet
  → Suggested action: value drop if relevant signal today

  🧊 COOLING (one more try):
  [Name] (score: 2, ↓) [Stage: Warm Up] [DP: Prospect] - liked one post 10 days ago, nothing since
  → Suggested action: comment on their next post, don't DM

  ❄️ COLD (auto-closing soon):
  [Name] (score: -1) [Stage: First DM] [DP: Outreach Sent] - 3 touches, 0 clicks, 0 responses, 16 days
  → Auto-closes at next check (RULE-016)
  ```

- **Relationship context inline (C2):** Each prospect line includes [Stage: X] and [DP: Y] so the founder sees relationship status without cross-referencing the pipeline section. No more checking 4 different sections to understand one prospect's state.

- **Rules:**
  - Hot prospects get Quick Win follow-up Actions created automatically
  - Warm prospects get value-drop Actions if a matching signal exists today
  - Cool prospects get ONE more touch suggestion, low pressure
  - Cold prospects: system handles via RULE-016, no action needed from founder
  - Trend arrows show momentum: someone going from Warm to Hot is more important than someone who's been Warm for 2 weeks
  - The score replaces all other engagement reporting in the briefing. No more checking 4 different sections to figure out who cares.

**Step 5.85 - Existing pipeline follow-up (daily, REQUIRED):**
> **HARNESS:** Log as `5.85_pipeline_followup`. Result = overdue count + follow-ups generated. This step CANNOT be skipped. New leads (5.9) do NOT replace following up with existing warm prospects.

This step ensures existing warm relationships don't go cold while chasing new ones. New lead sourcing (5.9) runs AFTER this, not instead of it.

**1. Pull overdue actions from Notion Actions DB:**
- Query Actions DB for Priority = Today or This Week with Due date <= today
- Also pull any actions with no Due date but Priority = Today
- Sort by age (oldest first)

**2. Pull warm DP prospects needing follow-up:**
- Query Contacts DB for Type = Design Partner AND Status = Warm or Active
- Filter for Last Contact > 7 days ago
- These people are going cold. They need a touch.

**3. Pull warm investor follow-ups:**
- Query Investor Pipeline DB for Stage != Passed AND Next Date <= today
- These have scheduled follow-up dates that are due

**4. For each overdue item, generate ONE of:**
- A copy-paste follow-up email/DM (if ball is in your court)
- A "check status" note (if ball is in their court and it's been 7+ days)
- A "close/park" recommendation (if 14+ days, 3+ touches, no response)

**5. Output: Add to HTML as "Pipeline Follow-ups" section (accent: purple)**
- This section appears BEFORE new leads in the HTML
- Each item has: person name, what's overdue, copy-paste follow-up, time estimate
- Items sorted by relationship value (active DPs first, then warm DPs, then investors, then general)

**Loop auto-close (action_created):** When querying Notion Actions DB for overdue items, also check for any actions that have been completed (moved to Someday by the stale action cleanup in Step 1, or manually marked done by founder). Cross-reference against open loops of type `action_created`:
```bash
python3 q-system/.q-system/loop-tracker.py close <loop_id> "action completed in Notion" "auto_notion"
```

**Loop opening (REQUIRED for every follow-up generated):**
Every follow-up email or DM generated in 5.85 MUST open a loop (or update touch_count on existing loop):
```bash
# For email follow-ups:
python3 q-system/.q-system/loop-tracker.py open email_sent "Person Name" "Follow-up context" "" "E1" "Next follow-up text..."
# For DM follow-ups:
python3 q-system/.q-system/loop-tracker.py open dm_sent "Person Name" "Follow-up context" "" "DM1" "Next follow-up text..."
```
If the person already has an open loop, `loop-tracker.py open` will auto-increment touch_count instead of creating a duplicate.

**Rules:**
- MINIMUM 3 follow-up items per day in the HTML, even if nothing is technically "overdue"
- If nothing is overdue, surface the 3 warmest relationships that haven't been touched in 5+ days
- New lead sourcing (5.9) is exciting but follow-ups close deals. Follow-ups come first.
- Every follow-up gets an action card in the morning log

---

**Step 5.86 - Open loop review (daily, CANNOT BE SKIPPED):**
> **HARNESS:** Log as `5.86_loop_review`. This step CANNOT be skipped. Open loops are the #1 AUDHD failure mode. New leads (5.9) do NOT replace closing existing loops.

This is the core loop-closing forcing function. It reads all open loops and generates follow-up actions.

1. Run `python3 q-system/.q-system/loop-tracker.py list 1` to get all loops at level 1+ (3+ days old)
2. **Level 1 loops (3-6 days):** Generate a copy-paste follow-up message for each. Add as action card in morning log. Show in Pipeline Follow-ups section of HTML with yellow `daysAgo` tag.
3. **Level 2 loops (7-13 days):** Generate follow-up AND flag prominently. Show at top of Pipeline Follow-ups with red `daysAgo` tag. If touch_count >= 3 on same channel, switch to a different channel.
4. **Level 3 loops (14+ days):** Present forced choice to founder:
   - "Act now" - generate follow-up, reset to level 2
   - "Park" - close loop, re-engage only on trigger
   - "Kill" - close permanently
   **Step 8 gate BLOCKS if any level 3 loops are unresolved.** The HTML cannot be generated with open level 3 loops.
5. **For each follow-up generated:** Open or update the loop with new touch_count
   ```bash
   python3 q-system/.q-system/loop-tracker.py touch <loop_id>
   ```
6. **Output to HTML:** "Open Loops" section (accent: red, position 2 in section order). Only level 2+ loops show here. Level 0-1 appear as a count in FYI.
```bash
python3 q-system/.q-system/log-step.py DATE 5.86_loop_review done "X loops reviewed, Y follow-ups generated, Z force-closed"
```

---

**Step 5.9 - Lead sourcing: find people screaming about the problem we solve (daily):**
> **HARNESS:** Log as `5.9_lead_sourcing`. Result = query count + platform count + qualified prospect count. Must include ALL platforms (LinkedIn, Reddit, X, Medium). If any platform was skipped, log as `partial` with reason. Save raw results to `output/lead-gen/` immediately (context-saving rule). Create action cards for each Tier A/B prospect's outreach message.

This step finds practitioners and leaders who are actively feeling the pain {{YOUR_PRODUCT}} solves. The goal is to produce 5-10 qualified prospects per day with copy-paste-ready, personalized outreach - like the Mar 9 run that found Paul Hutelmyer (built Detect Hub at Target), Chris Long (created DetectionLab), and Aaron Martin ("Detection engineering doesn't scale just because you write more rules").

**THIS STEP HAS 4 PHASES. DO NOT SKIP ANY. DO NOT REPLACE CLAUDE QUALIFICATION WITH A KEYWORD FILTER.**

---

**PHASE 1 - COLLECT (Chrome + Reddit MCP + RSS + Apify[X only], 3-5 min):**

Run Chrome (LinkedIn), Reddit MCP, RSS feeds via WebFetch (Medium), and Apify (X only) to gather raw posts. Save all raw results to `output/lead-gen/[platform]-YYYY-MM-DD-raw.json`.

**1a. LinkedIn post search** via Chrome browser:
- Navigate to `https://www.linkedin.com/search/results/content/?keywords=ENCODED_QUERY&sortBy=date_posted` via `mcp__claude-in-chrome__navigate`
- Use `mcp__claude-in-chrome__read_page` or `mcp__claude-in-chrome__get_page_text` to extract the first 10 results
- Sort by DATE (not relevance) to get recent posts from people actively feeling pain NOW
- If Chrome fails for LinkedIn: skip LinkedIn leads for this run. No Apify fallback.
- Run 4 queries per day from the ROTATION below. **USE THE EXACT ROTATION QUERIES, NOT GENERIC SUBSTITUTES.** The rotation queries use quoted first-person phrases ("we built", "our detections") that filter for practitioners describing their own pain. Generic queries ("who owns detection", "lessons learned incident response") return educational content and vendor posts. If the rotation says Day 2 = "we built" detection pipeline, the LinkedIn search URL must contain exactly `%22we%20built%22%20detection%20pipeline`.

**1b. Reddit search** via Reddit MCP (`mcp__reddit__*`):
- **PRIMARY: Reddit MCP** - Use `mcp__reddit__search_subreddit` with `subreddit=SUBREDDIT`, `query=SEARCH_TERMS`, `limit=10`, `sort="new"`.
  - Returns structured data: title, URL, author, full content text, score (upvotes), comment count.
  - No two-pass needed. Full post text and engagement data included in MCP response.
  - For high-scoring leads that need deeper context, call `mcp__reddit__get_post` with the permalink to get the full comment tree.
- **NO FALLBACK:** If Reddit MCP fails, skip Reddit leads for this run. Do NOT use Chrome for Reddit.
- Rotate 2 subreddits per day: Mon/Wed/Fri = r/cybersecurity + r/netsec, Tue/Thu = r/blueteamsec + r/AskNetsec
- Use Reddit-specific queries from the REDDIT QUERY section below (tool-seeker queries work best on Reddit)
- Pull last 30 days (not 7 - security threads stay relevant longer)
- **VALIDATION:** After results return, check that ALL results come from the target subreddits.

**1c. X/Twitter search** via Apify `apidojo~tweet-scraper`:
- **Two modes, run both:**
  - **Search mode:** 2 queries from Tool-seeker category. Save raw results.
  - **Profile mode:** Pull last 48h tweets from monitored handles: @BushidoToken, @clintgibler, @RyanGCox_, @obadiahbridges. These are the X equivalent of LinkedIn post scraping - gives you real tweets to reply to.
- DO NOT USE: `quacker~twitter-scraper` (untested, use `apidojo~tweet-scraper` which is confirmed working)
- If Apify fails, fall back to Chrome: navigate to `https://x.com/search?q=SEARCH_TERMS&f=live`, read first 10 results.
- If both fail, note "X scrape failed - [error]" in the hitlist. Do NOT substitute with template replies to handles you haven't actually scraped.

**1d. Medium search** via RSS feeds + WebSearch:
- **PRIMARY: RSS feeds** via WebFetch on `https://medium.com/feed/tag/TAG` for relevant tags from market-intelligence.md
- **SUPPLEMENT: WebSearch** for `site:medium.com SEARCH_TERMS 2025 OR 2026`
- Run 2 queries per day rotating across pain categories. Examples:
  - CAT1: tag `detection-engineering` RSS + WebSearch `site:medium.com "detection engineering" broken management 2025 OR 2026`
  - CAT4: tag `incident-response` RSS + WebSearch `site:medium.com "incident response" "lessons learned" security operations 2025 OR 2026`
  - CAT6: WebSearch `site:medium.com "compliance theater" security 2025 OR 2026`
  - CROSS: WebSearch `site:medium.com "security silos" teams 2025 OR 2026`
- Target: first-person practitioner articles, not vendor content or tutorials
- WebFetch prompt for RSS: "Extract all articles. For each return: title, article URL, author name, date, and first 300 characters of content. Return as a numbered list."
- WebFetch returns structured text (NOT raw XML). Score results directly from the response.
- **FALLBACK: Chrome** if both RSS and WebSearch fail - navigate to Google search with the same `site:medium.com` query
- NOTE: This finds articles, not people directly. Extract author names from Medium URLs/titles, then cross-reference on LinkedIn for engagement.

**1e. GitHub search** (Mondays only, via GitHub API or Chrome):
- Search for new/updated security operations repos (not just detection - include IR, compliance, cross-team)
- Check for new contributors/stars on watched repos
- THIS IS THE HIGHEST-SIGNAL SOURCE - tool builders are the best prospects

---

**QUERY LIBRARY (6 pain categories matching the 6 teams in demo2):**

**CRITICAL:** {{YOUR_PRODUCT}} is NOT a single-use tool. Queries MUST span all pain surfaces defined in `my-project/current-state.md`, not just one vertical. Comments MUST match the person's actual pain - never steer toward one area if they posted about a different one.

**CATEGORY 1 - SOC / Detection Engineering:**
- `"built internally" detection management` OR `"built our own" detection`
- `"we built" detection pipeline` OR `"we built" detection platform`
- `"our detections" stale` OR `"our detections" broken` OR `"no one maintains"`
- `"nobody owns" detection` OR `"who owns" "these detections"`
- `"detection engineering" broken` OR `"detection engineering" "doesn't scale"`

**CATEGORY 2 - IAM / Identity Security:**
- `"conditional access" "keeps breaking"` OR `"Okta policies" "out of date"`
- `"identity" "security gap"` OR `"identity" "nobody owns"`
- `"IAM" "tribal knowledge"` OR `"who manages" "access policies"`
- `"MFA fatigue"` + operations OR `"identity" "incident response"`

**CATEGORY 3 - Endpoint / EDR:**
- `"EDR rules" "nobody updates"` OR `"CrowdStrike" "custom rules" manage`
- `"endpoint" "detection gap"` OR `"our EDR" "doesn't catch"`
- `"built our own" endpoint` OR `"homegrown" EDR`

**CATEGORY 4 - IR / Incident Response:**
- `"red team report" "never implemented"` OR `"sits in a drawer"`
- `"postmortem" "same thing again"` OR `"lessons learned" "nobody follows"`
- `"we keep" "getting breached"` OR `"same incident twice"`
- `"incident response" "playbook" outdated` OR `"IR" "tribal knowledge"`

**CATEGORY 5 - Email Security:**
- `"phishing" "same campaign"` OR `"email rules" "out of date"`
- `"transport rules" manage` OR `"email security" "nobody owns"`
- `"Proofpoint" OR "Mimecast" "custom rules"` + manage/lifecycle

**CATEGORY 6 - GRC / Compliance:**
- `"compliance theater"` + security operations
- `"audit" "scramble"` OR `"compliance" "manual" "spreadsheet"`
- `"GRC" "disconnect" security` OR `"controls" "nobody validates"`
- `"SOC 2" "detection" evidence` OR `"compliance" "security operations" gap`

**CATEGORY 7 - Practitioner Burnout / Firefighting Fatigue (added Mar 16, USER-DIRECTED):**
- `"tired of" "same fires"` OR `"fighting fires" security` OR `"burnt out" security`
- `"same incident" "over and over"` OR `"we keep seeing" "same attack"`
- `"pulled the same report" security` OR `"redo" "for leadership"` OR `"reporting the same thing"`
- `"burnout" SOC` OR `"burnout" "detection engineer"` OR `"burnout" "threat intel"`
- `"nobody reads" postmortem` OR `"shelf" report security` OR `"shelfware"`
- `"left security" burnout` OR `"quit" CISO` OR `"career change" cybersecurity`
- `"what's the point" security` OR `"nothing changes" security operations`

**Why this category matters:** These people are the internal champions who would push for {{YOUR_PRODUCT}} bottom-up. They see the pattern, can't fix it structurally, and are posting about their frustration. Highest authenticity for engagement because the founder lived this.

**CROSS-CATEGORY (highest signal - spans multiple teams):**
- `"security silos"` OR `"teams don't talk"` OR `"nobody connects"`
- `"security doesn't learn"` OR `"breached the same way twice"`
- `"our SOC" "tribal knowledge"` OR `"when people leave" security`
- `"is there a tool" security operations lifecycle` OR `"wish there was" security governance`
- `"homegrown" security` OR `"internal tool" security lifecycle`

**Rotation schedule:** 4 queries per day. Always include at least 2 different categories. **AUTO-ROTATION (C1):** Read `memory/morning-state.md` field `last_sourcing_day` (1-6). Auto-increment to next day. If missing or corrupted, start at Day 1. After running queries, write back the current day number. The founder NEVER needs to remember or specify which rotation day to use.

**Rotation (7-day cycle, cross-category coverage):**
- Day 1: CAT1 "built internally" detection + CAT4 "postmortem same thing" + CAT7 "tired of same fires" + CROSS "security silos"
- Day 2: CAT2 "conditional access" + CAT3 "EDR rules nobody" + CAT5 "phishing same campaign" + CROSS "security doesn't learn"
- Day 3: CAT1 "nobody owns detection" + CAT4 "red team report never" + CAT7 "burnout SOC" + CROSS "tribal knowledge"
- Day 4: CAT2 "IAM tribal knowledge" + CAT3 "built our own endpoint" + CAT5 "transport rules manage" + CROSS "is there a tool"
- Day 5: CAT1 "our detections stale" + CAT4 "we keep getting breached" + CAT7 "nobody reads postmortem" + CROSS "teams don't talk"
- Day 6: CAT2 "identity security gap" + CAT3 "endpoint detection gap" + CAT5 "email security nobody owns" + CROSS "homegrown security"
- Day 7: CAT6 "compliance theater" + CAT6 "audit scramble" + CAT7 "same incident over and over" + CROSS "what's the point security"
- Day 8: Repeat Day 1

**Reddit-specific queries (rotate across categories):**
- `"is there a tool" detection` OR `"does anyone use" detection management`
- `"how do you manage" security rules` OR `"how do you track" detections`
- `"alert fatigue" "what do you do"` OR `"SOC burnout" advice`
- `"compliance" "security" "manual process"` OR `"GRC" "evidence collection"`
- `"incident response" "playbook" manage` OR `"postmortem" "follow up"`
- `"burnout" cybersecurity` OR `"tired" "same problems"` OR `"want to quit" security`
- `"same incident" "again"` OR `"fighting fires" security` OR `"nothing changes"`
- `"career change" cybersecurity` OR `"leaving security"` OR `"burnt out" SOC`

**Medium-specific searches:**
- Search via RSS feeds (WebFetch on `medium.com/feed/tag/TAG`) + WebSearch (`site:medium.com`) for Medium articles about: security operations pain, detection engineering challenges, IR process failures, compliance automation gaps, security team silos
- Target authors who write from first-person practitioner experience (not vendors)
- Fallback: Chrome Google search with `site:medium.com` queries

**GitHub-specific searches (Mondays):**
- `"detection engineering" framework` OR `management` OR `lifecycle` (sort by recently updated)
- `"detection as code" management`
- `"security automation" governance` OR `"security operations" framework`
- `sigma` OR `YARA` rule management governance
- New stars/forks on watched repos: SigmaHQ/sigma, rabobank-cdc/DeTTECT, Atomic Red Team
- Key maintainers to track: Florian Roth (@Neo23x0), Nasreddine Bencherchali (@nasbench), Marcus Bakker

---

**PHASE 2 - QUALIFY AND RANK (Claude reads every result, 5-10 min):**

**CONTEXT-SAVING: Process in batches of 10.** Read 10 raw results from the saved JSON files. Score them. Discard anything below 10. Move to next batch. Never hold all raw results in context at once. After scoring all batches, combine the surviving results (score 10+) into one ranked list for Phase 3.

**DO NOT use a Python keyword filter. Claude reads every post and applies judgment.**

**Step 1: Discard (fast pass - eliminate noise first):**
Discard immediately if ANY of these are true:
- Not first-person ("organizations should", "best practices for", "here's how to")
- Vendor promoting their own product (check headline for company/product they sell)
- Student/aspiring ("looking for my first role", "just completed certification")
- Recruiter/hiring post as main point
- Post older than 3 months
- Not security-related (query noise - salon software, Tesla, etc.)

**Step 2: Score every surviving result on 5 dimensions (1-5 each, max 25):**

| Dimension | 5 pts | 3 pts | 1 pt |
|-----------|-------|-------|------|
| **Pain signal** | Built a tool to solve this / "I wish there was X" | Strong opinion about what's broken | General discussion, no personal frustration |
| **First-person proof** | "We built" / "Our team" / names their company | "I've seen" / "In my experience" | Third-person or hypothetical |
| **Role fit** | Security leader/practitioner at enterprise (CISO, Dir SecOps, Det Eng Lead, IR Manager, GRC Lead) | Security IC or adjacent role (SOC analyst, compliance analyst, AppSec) | Non-security role tangentially discussing security |
| **Engagement opportunity** | Post has a question or open problem we can genuinely add value to | Post has a take we can build on with a thoughtful comment | Post is closed/declarative, hard to add value without pitching |
| **Multi-team pain** | Describes cross-silo problem (exactly {{YOUR_PRODUCT}}'s value prop) | Describes single-team problem {{YOUR_PRODUCT}} solves (detection OR IR OR compliance etc.) | Single-tool problem (e.g., "how do I write a Splunk query") |

**Composite score = sum of 5 dimensions (max 25)**

| Score | Tier | Action |
|-------|------|--------|
| 20-25 | **A - Send today** | Connection request + comment on their post. Top priority. |
| 15-19 | **B - Engage today, connect tomorrow** | Comment on their post today. Connection request tomorrow. |
| 10-14 | **C - Warm list** | Add to engagement hitlist for future warming. No outreach yet. |
| Below 10 | **Discard** | Not worth the time. |

**Step 2.5: Market intelligence extraction (during scoring, not a separate pass):**
While scoring each post, also evaluate whether it has **canonical value** beyond engagement. Not every post qualifies - only capture genuinely new signal. Apply these lenses:

| Lens | What to capture | Route to |
|------|----------------|----------|
| **Problem language** | Verbatim phrases where practitioners describe a pain we solve in THEIR words | `canonical/market-intelligence.md` Problem Language section + consider for `canonical/talk-tracks.md` |
| **Category signal** | "I wish there was..." / "Why doesn't someone build..." / describing our category without knowing it | `canonical/market-intelligence.md` Category Signals section |
| **Objection preview** | Concerns about tools like ours, skepticism about AI in security, "we tried X and it didn't work" | `canonical/market-intelligence.md` Objection Previews + `canonical/objections.md` if new |
| **Competitive intel** | Praise or complaints about tools in our landscape (detection platforms, TIPs, SOAR, GRC tools) | `canonical/market-intelligence.md` Competitive Intel + `my-project/competitive-landscape.md` if significant |
| **Buyer process** | How they evaluate, budget, get approval, implement. Procurement friction, decision timelines | `canonical/market-intelligence.md` Buyer Process section |
| **Narrative check** | Does this confirm or contradict our positioning? If 5+ people describe the problem differently than we do, flag it | `canonical/market-intelligence.md` Validation Log |

**Rules:**
- Only capture if it's genuinely new signal (not a repeat of what we already have)
- Verbatim quotes are more valuable than paraphrases
- One high-signal post with canonical value > 10 engagement-only posts
- If a post scores 20+ AND has canonical value, it's a priority capture
- Log entries go to `canonical/market-intelligence.md` with date, platform, author, URL, verbatim quote, lens, and one-sentence insight
- If 3+ posts in a single day point to the same theme, flag it as a **market pattern** in the morning briefing

**Step 3: Rank and select top results across ALL platforms:**
- Combine all scored results from LinkedIn + Reddit + Medium + X into one ranked list
- Sort by composite score descending
- **Daily cap: Top 10 into the engagement hitlist** (max 5 Tier A, max 5 Tier B)
- If more than 5 Tier A results, pick the ones with highest multi-team pain scores
- Include platform source and post URL for each

**Step 4: Output format for the HTML hitlist:**
For each selected result, output:
- Name, role, company (if known), platform
- Composite score and tier (A/B/C)
- Which pain category they match (CAT1-6 or CROSS)
- Their post summary (1 sentence)
- Copy-paste comment/reply
- Post URL

**Scoring tiebreakers (when composite scores are equal):**
1. Multi-team pain > single-team pain
2. Tool builders > pain expressers > opinion holders
3. Enterprise role > IC role
4. More recent post wins
5. LinkedIn > Medium > Reddit > X (based on relationship-building potential)

---

**PHASE 3 - PRODUCE OUTREACH (Claude generates, 5-10 min):**

Using the ranked results from Phase 2 (Tier A and Tier B only), produce a file at `output/design-partner/problem-language-outreach-YYYY-MM-DD.md` following the exact format of the Mar 9 file. Structure:

**TIER A - Send Today (max 5):**
Tool builders and people expressing active pain (signal score 4-5). Connection request references THEIR specific post/tool.

Each entry includes:
- Name, title, platform
- "Why them" - 1 sentence explaining what makes them a good prospect
- **Full post text** (quoted block - the actual text they wrote, pulled during Phase 2 qualification)
- Copy-paste connection request (under 300 chars, references their specific words)

**TIER B - Warm Up First, Send Tomorrow (remaining):**
Strong opinion holders and community figures (signal score 3-4). Requires engaging with their content first.

Each entry includes:
- Name, title, platform
- "Why them" - 1 sentence
- **Full post text** (quoted block - the actual text they wrote)
- Pre-work: which post to comment on today (with a ready comment written against the actual post text)
- Copy-paste connection request for tomorrow

**Follow-up DM templates** (for after connection is accepted):
- For builders: ask what their tool couldn't solve
- For pain-expressers: ask what they've tried
- For opinion-holders: ask what they think is missing in the market

**The "only for this person" test:** Read every connection request out loud. Could it be sent to anyone else? If yes, rewrite with something specific to their post/tool/company.

**Loop opening (REQUIRED for every outbound action in the hitlist):**
Every DM, comment, connection request, and X reply generated in 5.9b MUST open a loop:
```bash
# For each LinkedIn comment:
python3 q-system/.q-system/loop-tracker.py open comment_posted "Person Name" "Topic of post" "" "C1"
# For each connection request:
python3 q-system/.q-system/loop-tracker.py open connection_request_sent "Person Name" "Why connecting" "" "CR1"
# For each DM:
python3 q-system/.q-system/loop-tracker.py open dm_sent "Person Name" "DM context" "" "DM1" "Follow-up text if no reply..."
# For each X reply:
python3 q-system/.q-system/loop-tracker.py open comment_posted "Person Handle" "X reply topic" "" "X1"
# For each Reddit comment:
python3 q-system/.q-system/loop-tracker.py open comment_posted "Thread title" "Reddit comment context" "" "R1"
```
If a loop-tracker.py open call is missing for any hitlist item, Step 5.9b is INCOMPLETE.

**Prediction logging:** For each Tier A/B prospect, log a prediction to `memory/working/predictions.jsonl`:
```jsonl
{"date":"YYYY-MM-DD","prospect":"Name","channel":"linkedin_connect","prediction":"will_accept","confidence":0.6,"style":"C1","outcome":null,"outcome_date":null}
```
Style codes: V1 (value drop), Q1 (question), P1 (peer observation), C1 (content reference), W1 (warm intro). These are used for A/B analysis monthly.

---

**PHASE 4 - PIPELINE (automated, Notion updates):**

Every qualified prospect (score 3+) enters the unified pipeline:

```
DISCOVERY (5.9) -> QUALIFY -> CREATE CONTACT -> CREATE TRACKER ENTRY -> ENGAGEMENT HITLIST (5.9b) -> DM/ACCEPT DETECTION (3.8) -> RELATIONSHIP PROGRESSION
```

1. **Check Notion Contacts DB** (DB cabba10d-cd5d-4cff-b042-3241a2be18b5) - skip if they already exist
2. **Create Notion Contact** (Type: Design Partner, DP Status: Prospect, Source: Problem-Language Search, Notes: post URL + problem category + signal score + date found)
3. **Create Notion LinkedIn Tracker entry** (Type: Connection Request, Status: Pending, Date: today, linked to Contact)
4. **Create Notion Action** (Type: LinkedIn, Energy: Quick Win, Time: 5 min, Priority: Today for Tier A / This Week for Tier B)
5. **Open a loop for each qualified lead** so they don't get forgotten:
   ```bash
   # For Tier A/B leads that got a connection request:
   python3 q-system/.q-system/loop-tracker.py open lead_sourced "Person Name" "Tier A - pain signal + role fit" "" ""
   ```
   The `lead_sourced` loop closes when the lead gets a first touch (connection request accepted + first DM sent, which becomes a `dm_sent` loop).
6. **Prospect flows automatically into subsequent morning routine steps:**
   - Step 5.9b picks them up for daily engagement (comment on their posts while waiting for accept)
   - Step 3.8 detects when they accept the connection request (10-day lookback)
   - On accept: Step 3.8 auto-generates first DM, advances to Stage 3, AND closes the `lead_sourced` loop + opens a `dm_sent` loop
   - After DM sent: Step 3.8 monitors for reply (10-day lookback)
   - On reply: `dm_sent` loop auto-closes, relationship advances, next action generated
   - On timeout (10 days no accept): deprioritized

**Re-engagement for existing contacts:**
If someone already in Contacts DB posts about a {{YOUR_PRODUCT}} problem:
1. Update Contact notes with new post URL + date
2. Flag in morning briefing: "[Name] just posted about [topic] - they're feeling the pain right now"
3. Add to Step 5.9b engagement hitlist as TOP PRIORITY
4. If Cooling/Cold status: re-warm with a comment on their post

**Activity tracking (14-day window):**
For prospects found in the last 14 days (Status: Prospect or Outreach Sent):
1. Use Chrome to navigate to their LinkedIn profile and check latest posts (last 48h)
2. If they posted again about the problem: boost priority ("posting repeatedly")
3. If they engaged with founder's content: flag as WARM SIGNAL
4. Track in LinkedIn Tracker notes

---

**RULES:**
- Max 5 new connection requests per day from this step (LinkedIn jail prevention)
- Connection requests reference THEIR words, not {{YOUR_PRODUCT}}. No pitch.
- Reddit comments must be genuinely helpful. No pitch. Share experience.
- **Full post text required:** During Phase 2 qualification, pull and save the FULL text of every qualified prospect's post. Outreach copy in Phase 3 must be written against the actual post, never a summary. If Chrome doesn't show full text, click into the post to expand and read full content.
- **No resume name-dropping:** Never list company names (Google, Meta, ElevenLabs) or years of experience in outreach copy. Use "everywhere I've worked" instead.
- Track daily search rotation in memory/morning-state.md
- If Chrome fails for LinkedIn: skip. If Reddit MCP fails: skip Reddit (no Chrome fallback). If RSS fails for Medium: try Chrome. If Apify fails for X: try Chrome.
- Save raw results to `output/lead-gen/` for trend analysis
- **On days when Phase 1 returns zero qualified results after Phase 2 filtering:** That's fine. Better 0 real prospects than 5 fake ones. Log "no qualified prospects today" and move on.

---

**BRIEFING OUTPUT (appended to morning briefing):**
```
LEAD SOURCING (Step 5.9)

Queries: [list 4 queries run today]
Raw results: [X] LinkedIn, [X] Reddit, [X] X/Twitter
After qualification: [X] prospects (score 3+)

TIER A - SEND TODAY (copy-paste ready):
1. [Name] - [Title] at [Company] (signal: [score])
   Why: [1 sentence - what makes them a prospect]
   Post: "[their exact words, 100 chars]"
   Connection request: "[ready to paste]"

TIER B - WARM UP FIRST:
1. [Name] - [Title] (signal: [score])
   Pre-work: Comment on their post about [topic]
   Comment: "[ready to paste]"
   Connection request (send tomorrow): "[ready to paste]"

RE-ENGAGEMENT:
[Name] just posted about [topic] - comment on their post today

REDDIT THREADS:
[subreddit] - "[title]" ([X] upvotes)
Comment: "[ready helpful comment, no pitch]"

GitHub (Mondays only):
[repo] - [new activity] - [maintainer to engage]
```

**Step 5.9b - Daily Engagement Hitlist (daily, COPY-PASTE READY, AUDHD rules enforced):**

> **HARNESS: Action cards.** For every engagement item generated:
> ```bash
> python3 q-system/.q-system/log-step.py DATE add-card C1 linkedin_comment "Person Name" "Comment text..." "https://linkedin.com/post-url"
> python3 q-system/.q-system/log-step.py DATE add-card C2 x_reply "Person Name" "Reply text..." "https://x.com/post-url"
> python3 q-system/.q-system/log-step.py DATE add-card C3 connection_request "Person Name" "Request note..." "https://linkedin.com/in/person"
> python3 q-system/.q-system/log-step.py DATE add-card C4 reddit_comment "u/username" "Comment text..." "https://reddit.com/thread-url"
> ```
> Types: `linkedin_comment`, `x_reply`, `connection_request`, `reddit_comment`, `linkedin_dm`, `email`
> **URL field is required** - the founder needs the link to navigate to the post.
> NEVER log to LinkedIn Tracker, Contacts DB, or any state file until `founder_confirmed: true` (next session's Step 0b).
> ```bash
> python3 q-system/.q-system/log-step.py DATE 5.9b_engagement_hitlist done "X items across Y types, X action cards"
> ```

This step generates the founder's daily engagement actions with zero searching required. Everything is copy-paste ready. Per AUDHD executive function skill: every hitlist item includes (1) the actual copy-paste text inline, (2) a direct link to the post/tweet/thread, (3) time estimate, (4) energy tag. NEVER output a hitlist item that says "copy-paste from section above." The text must be RIGHT THERE.

- **Pull engagement targets from Notion Contacts DB:**
  - Query all contacts where Type = Design Partner, VC, CISO, Connector, Advisor, Practitioner
  - Filter to those with a LinkedIn URL populated
  - Cross-reference Notion LinkedIn Tracker DB: exclude anyone engaged in the last 7 days (1 comment/person/week rule)
  - Prioritize: (1) Hot prospects from Step 5.8, (2) Design Partner prospects not yet connected, (3) Connectors/influencers, (4) VCs with upcoming meetings, (5) Everyone else

- **Scrape recent posts via Chrome** (navigate to each target's LinkedIn profile):
  - **CONTEXT-SAVING: Cap at 10 targets** (not 15). Pick the 10 highest-priority from the filtered list.
  - Navigate to each target's profile via Chrome, read last 48h posts (process sequentially)
  - Extract: post text, post URL, engagement count, topic
  - Skip reposts/shares (only original content worth commenting on)

- **Generate copy-paste comments** for each post found:
  - Style by pool: VCs get domain insight, practitioners get peer validation, connectors get amplification
  - 2-3 sentences max, no {{YOUR_PRODUCT}} pitch
  - Reference something specific from their post (not generic "great insights")
  - Must pass test: "Does this comment add value to the conversation?"
  - **VOICE RULE: Stay on the person's topic. Do NOT steer every comment toward detection engineering.** The founder's credibility is 12 years of security operations leadership (Google, Meta, ElevenLabs), not "detection engineering" specifically. If someone posts about ownership gaps, comment about ownership gaps. If someone posts about governance, comment about governance. If someone posts about silos, comment about silos. Only mention detection if THEY mentioned detection. The goal is to be a thoughtful practitioner voice on THEIR topic, not to position yourself as a detection expert. Detection is the wedge artifact, not the founder's identity.

- **Also pull X/Twitter activity** for contacts with X handles:
  - Use Apify `apidojo~tweet-scraper` for last 48h tweets from key handles (Apify is X-only)
  - Generate copy-paste replies (1-2 sentences, sharper than LinkedIn)
  - Same voice rule: reply to what THEY said. Don't pivot to detection.

- **Output appended to morning briefing (COPY-PASTE READY):**
  ```
  💬 DAILY ENGAGEMENT HITLIST (Step 5.9b) - [X] actions, ~[X] min total

  LINKEDIN COMMENTS (copy-paste, then click link to post):

  1. [Name] ([pool]) - [Company]
     Post: "[first 120 chars]..."
     🔗 [LinkedIn post URL]
     💬 Copy-paste comment:
     "[ready comment, 2-3 sentences]"
     ⏱️ 3 min | Energy: Quick Win

  2. [Name] ([pool]) - [Company]
     Post: "[first 120 chars]..."
     🔗 [LinkedIn post URL]
     💬 Copy-paste comment:
     "[ready comment, 2-3 sentences]"
     ⏱️ 3 min | Energy: Quick Win

  X/TWITTER REPLIES (copy-paste):

  1. @[handle] ([Name])
     Tweet: "[tweet text]"
     🔗 [tweet URL]
     💬 Copy-paste reply:
     "[ready reply, 1-2 sentences]"
     ⏱️ 2 min | Energy: Quick Win

  CONNECTION REQUESTS TO SEND TODAY (max 5):

  1. [Name] - [Role] at [Company]
     🔗 [LinkedIn profile URL]
     💬 Copy-paste request:
     "[personalized connection request, under 300 chars]"
     ⏱️ 2 min | Energy: Quick Win

  REDDIT THREADS TO COMMENT ON:

  1. r/[subreddit]: "[thread title]"
     🔗 [Reddit URL]
     💬 Copy-paste comment:
     "[helpful practitioner comment, no pitch, 3-5 sentences]"
     ⏱️ 5 min | Energy: Quick Win
  ```

- **VALIDATION CHECKPOINT (MANDATORY before proceeding to Step 6):**
  The engagement hitlist MUST attempt all 4 content types. Before moving on, verify:
  - [ ] LinkedIn comments: Chrome post scrape ran for top 10 targets. If 0 posts found, state "0 posts found in last 48h for [N] targets scraped" - do NOT silently skip.
  - [ ] X/Twitter replies: Apify tweet scrape (or Chrome fallback) ran for contacts with X handles. If 0 tweets found or no contacts have X handles, state the reason.
  - [ ] Connection requests: Generated from Step 5.9 qualified prospects + LinkedIn Tracker "Connect" stage contacts.
  - [ ] Reddit comments: Pulled from today's subreddit rotation (Step 5.9). If 0 relevant threads, state which subreddits were checked.
  If ANY type was skipped without explanation, the hitlist is INCOMPLETE. Go back and run the missing scrapes.
  NEVER generate the engagement hitlist as only connection requests. Connection requests alone is not an engagement hitlist.

- **Rules:**
  - Max 5 LinkedIn comments + 3 X replies + 5 connection requests + 2 Reddit comments per day
  - Total daily engagement time target: 25-35 min (all Quick Wins)
  - Every comment/reply gets logged to Notion LinkedIn Tracker after founder confirms posting
  - If no recent posts found for a contact, skip them (don't manufacture engagement)
  - **ENFORCE lead lifecycle rules** (`canonical/lead-lifecycle-rules.md`): Never generate a DM/email draft for a contact whose channel is dead (3+ unreturned messages on that channel). Never generate any outreach for a Parked contact unless a trigger fired. Never generate an email for a high-value contact (VC/CISO) with 3+ unreturned emails, suggest ambient engagement or warm intro instead.
  - Rotate through the full contact list over the week so nobody is engaged twice in 7 days
  - Create Notion Actions for each engagement item (Type: LinkedIn or Other, Energy: Quick Win, Time Est: 3 min or 5 min)

- **Notion updates after founder confirms:**
  - Create LinkedIn Tracker entry for each comment posted (Type: Comment, Date: today, linked to Contact)
  - Update Contact's last interaction date
  - Set Follow-up Date: 5-7 days out on LinkedIn Tracker entry

**Step 6 — Decision compliance check (SKIP if context is running low - Step 11 is more important):**
> **HARNESS:** Log as `6_decision_compliance`. If skipping due to context, log as skipped with reason "context budget".
- Read `canonical/decisions.md` → get all active RULE entries
- For each rule with a `Grep check`, run the grep across canonical files
- Flag any violations (a rule says "never say X" but file still says X)

**Step 7 — Positioning freshness check (SKIP if context is running low - Step 11 is more important):**
> **HARNESS:** Log as `7_positioning_freshness`. If skipping due to context, log as skipped with reason "context budget".
- Read `memory/morning-state.md` → check "Pending Propagation" section
- If there are unpropagated decisions, flag them
- Check if talk-tracks.md, current-state.md, and doc generators are consistent with decisions.md

**Step 7.5 — Checkpoint drift detection:**

Catches sessions that ended without `/q-checkpoint` or `/q-end`.

- **Read `memory/morning-state.md`** -> get `Last checkpoint` timestamp
- **Read `my-project/progress.md`** -> get date of most recent log entry
- **Check canonical file modification times:** Use `ls -la` on `canonical/*.md` and `my-project/*.md`. If any file was modified AFTER the last checkpoint timestamp, those changes were made in a session that didn't checkpoint.
- **Drift detected if:** file mtime > last checkpoint timestamp AND no progress.md entry covers those changes
- **Output (only if drift found):**
  ```
  CHECKPOINT DRIFT DETECTED
  Last checkpoint: [date/time]
  Files modified since then: [list with mtimes]
  These changes were not logged. Running checkpoint now to capture them.
  ```
- **Auto-fix:** If drift is detected, run a lightweight checkpoint (log the changed files to `progress.md` with note "Auto-recovered from uncheckpointed session"). Update `morning-state.md` checkpoint timestamp.
- **Rules:**
  - This is a safety net, not a judgment. No pressure language. Just quietly fix it.
  - If no drift, skip this section entirely (no "All caught up!" noise).

**Step 8 — Output morning briefing (AUDHD executive function rules apply):**

> **GATE CHECK (mandatory before starting Step 8):**
> 1. Read the morning log from disk: `cat q-system/output/morning-log-DATE.json | python3 -c "import json,sys; steps=json.load(sys.stdin)['steps']; missing=[s for s in ['0f_connection_check','0a_checkpoint','0b_missed_debrief','0b.5_loop_escalation','0c_load_canonical','0d_load_voice','0e_load_audhd','1_calendar','1_gmail','1_notion_actions','1_notion_pipeline','3_linkedin_activity','3.5_dp_pipeline','3.8_dm_check','4.1_value_drops','5.8_temperature_scoring','5.85_pipeline_followup','5.86_loop_review','5.9_lead_sourcing','5.9b_engagement_hitlist','6_decision_compliance','7_positioning_freshness'] if s not in steps]; print(f'Missing: {missing}' if missing else 'All prior steps logged')"`
> 1b. Check for unresolved level 3 loops: `python3 q-system/.q-system/loop-tracker.py list 3` - if any exist, STOP. Force-close decisions must happen before HTML generation.
> 1c. Verify Deliverables Checklist (see preflight.md Section 5): day-specific content pieces, pipeline follow-ups, loop review items.
> 2. If missing list is empty: `python3 q-system/.q-system/log-step.py DATE gate-check step_8 true ""`
> 3. If missing list is not empty: `python3 q-system/.q-system/log-step.py DATE gate-check step_8 false "step1,step2"` then STOP and report.
> Cannot proceed until all prior steps are accounted for.

All output in this step must comply with the AUDHD executive function skill (loaded in Step 0e). Every item shown to the founder must be copy-paste ready or explicitly marked "needs your eyes." No dashboards without actions. No scores without recovery drafts. No cross-references. The briefing is a workbench, not a report.
```
📝 MISSED DEBRIEFS (from Step 1.1, only shown if any exist)
[person + time + pre-filled /q-debrief command]

▶️ START HERE
[single task - the highest-value, lowest-friction thing to do right now]
[why this one: "Hot prospect responded" or "5-min quick win clears your plate"]
[pre-filled command or copy-paste-ready text if applicable]

🎯 TODAY'S FOCUS (top 3-5 items, replaces scanning 15+ sections)
1. [action] - [why now] (Energy: Quick Win, 5 min)
2. [action] - [why now] (Energy: Quick Win, 10 min)
3. [action] - [why now] (Energy: Deep Focus, 20 min)
[These are the 3-5 most impactful things for today, pulled from all sections below. If you only have 30 minutes, do these. Everything else is gravy.]

📅 CALENDAR (this week)
[events list]

👤 MEETING PREP
[per-meeting briefs with LinkedIn + CRM + prep notes]

📧 UNLOGGED EMAILS (last 48h)
[emails from known contacts not in Interactions DB]

💬 LINKEDIN DMs + CONNECTIONS (from Step 3.8, auto-detected, 10-day lookback)
[Connection accepts with copy-paste first DMs]
[DM replies with copy-paste response suggestions]
[DMs needing reply with copy-paste responses]
[Pending connection request status]

🐦 X ACTIVITY
[new followers, replies to respond to, DM opportunities, QT/reply targets]
[X metrics on Mondays]

✅ ACTIONS DUE TODAY
[from Notion Actions DB]

🎯 INVESTOR PIPELINE
[upcoming follow-ups, status changes needed]

🤝 WARM INTRO OPPORTUNITIES (from Step 1.5)
[prospect -> connector -> suggested ask, or "No new prospects to match"]

🔄 LINKEDIN RE-ENGAGE
[comments with new activity + new post opportunities + overdue follow-ups]

📡 SIGNALS + X POSTS
[LinkedIn signal post + X signal post + X hot take + X BTS (Mon/Wed/Fri) + X visual idea (Wed)]

📨 INTEL DROPS TO SEND (from Step 4.1)
[signal-matched contacts with copy-paste DMs/emails and specific report links]

📊 SITE METRICS (Mondays only)
[weekly comparison or "N/A - not Monday"]

🌡️ PROSPECT TEMPERATURE (daily, from Step 5.8)
[Hot/Warm/Cool/Cold prospects with scores, trends, and one suggested action each]

🔍 UTM CLICK DETAIL (Mondays only, from Step 5.5)
[raw click data for score calibration]

💬 DAILY ENGAGEMENT HITLIST (from Step 5.9b) - COPY-PASTE READY

RELATIONSHIP ACTIONS (auto-generated, highest priority):
[Ready to connect: prospects with 2+ comments logged]
[Follow-up DMs due: accepted connections needing first DM]
[Value-drop DMs: first DM sent 7+ days ago, no reply]
[Replies to continue: prospects who responded]

NEW COMMENTS (warming up prospects):
[LinkedIn comments with post links + ready comments]
[X/Twitter replies with tweet links + ready replies]

OUTREACH:
[Connection requests to send today with ready messages]
[Reddit threads with ready comments]

Total: [X] actions ([Y] Quick Wins, [Z] Deep Focus, [W] People, [V] Admin), ~[X] min

🔎 PROBLEM-LANGUAGE PROSPECTS (from Step 5.9)
[new qualified decision-makers + champions talking about {{YOUR_PRODUCT}}'s problem]
[draft connection requests for each with inline copy-paste text and Copy button]
[Reddit threads with inline copy-paste comments and Copy button]

🧠 MARKET INTELLIGENCE (from Step 2.5 during lead sourcing)
[Only shown if new entries were added to canonical/market-intelligence.md today]
[New problem language captured: "verbatim quote" - [author], [platform]]
[New category signals: [description]]
[New objection previews: [description] - added to objections.md? yes/no]
[Market pattern alert: if 3+ posts pointed to same theme, flag it here]
[No action needed from founder - this is "here's what the market told us today"]

📣 MARKETING HEALTH (from Step 4.5)
[asset freshness, Gamma deck status, cadence progress, stale drafts]

🔄 PUBLISH RECONCILIATION (from Step 3.2, only if changes found)
[auto-detected publishes, direct publishes, cadence adjustments]

⚠️ DECISION COMPLIANCE
[any rule violations found — or "All clear"]

🔄 PENDING PROPAGATION
[positioning changes not yet in all files — or "All synced"]

🔧 CHECKPOINT DRIFT (from Step 7.5, only if drift found)
[files modified since last checkpoint, auto-recovery status]

📨 INVESTOR UPDATE DUE (from Step 9.5, only if triggered)
[trigger reason: "Design partner signed" or "30+ days since last update"]
[suggested: run /q-investor-update]
```

**Step 8.5 — Pick the "Start Here" task:**

Select ONE task for the top of the briefing. This removes the "what do I do first" decision. Selection priority (first match wins):

1. **Missed debrief** from Step 1.1 (memory decays fast, do it now) -> pre-fill `/q-debrief [Name]`
2. **Hot prospect responded** (DM reply or email from someone with temperature score 8+) -> pre-fill the reply draft
3. **Meeting in the next 2 hours** that needs prep -> link to meeting prep section
4. **Day-specific content task** (see cadence rules below) -> copy-paste-ready draft
5. **Quick Win action** with highest impact (value drop to a Hot prospect, or warm intro ask to a confirmed connector) -> pre-fill message

If nothing urgent, pick the easiest Quick Win to build momentum. Never pick a Deep Focus task as Start Here - mornings need a win, not a wall.

**TODAY'S FOCUS (CT1):** After picking Start Here, select the next 3-5 most impactful items across ALL sections. This is the "if you only have 30 minutes" list. Selection rules:
- Mix of Quick Wins (momentum) and at most 1 Deep Focus item
- Include any hot prospect responses, meeting prep due today, and time-sensitive content
- Include total time estimate for the focus list
- This replaces the need to scan 15+ briefing sections to figure out what matters

**Day-specific content cadence (built into Start Here and Daily Actions):**

| Day | Content Task | What to Show |
|-----|-------------|-------------|
| Monday | Sourcing day + Content intel | "It's Monday - sourcing day. Pipeline has [X] active prospects." |
| Tuesday | TL post (LinkedIn carousel + X card) | "It's Tuesday - TL post day. Draft + carousel below, copy-paste ready." |
| Wednesday | X visual post idea | "It's Wednesday - visual post day. Idea + caption below." |
| Thursday | TL post (LinkedIn carousel + X card) | "It's Thursday - TL post day. Draft + carousel below, copy-paste ready." |
| Friday | Medium article draft + header image | "It's Friday - Medium draft day. Outline + header image below." |
| Saturday | Substack newsletter draft + header | "It's Saturday - Substack draft day. Can expand your Medium piece or go original." |
| Sunday | Publish Medium + Substack | "It's Sunday - publish day. Medium + Substack ready to go." |

The day label appears in the Start Here section AND at the top of the Daily Actions page. The founder doesn't have to remember what day means what.

**Step 9 — Offer fixes + push actions to Notion:**

> **GATE CHECK (mandatory before starting Step 9):**
> Re-read morning log from disk (same check as Step 8, plus `8_briefing_output` and `8.5_start_here`).
> `python3 q-system/.q-system/log-step.py DATE gate-check step_9 true ""`
> If missing steps: `python3 q-system/.q-system/log-step.py DATE gate-check step_9 false "missing_step_ids"` then STOP.

- If violations or pending propagation found, offer to fix immediately
- If unlogged emails found, offer to create Notion interactions
- If LinkedIn follow-ups overdue, offer to generate comment suggestions
- **ALWAYS create Notion Actions** for every actionable item surfaced in the briefing (meeting prep, follow-ups due, emails to send, debriefs to run, LinkedIn re-engagements). Use Actions DB (DB 0718ee69-d9d0-473d-8182-732d21c60491). Set Energy, Time Est, Priority, Type, Due date, and Contact link for each.
- **Marketing actions from Step 4.5:** If stale assets found, create Action "Refresh stale marketing assets" (Energy: Deep Focus, Time: 30 min, Type: Other). If Gamma decks need review, create Action "Review Gamma deck for positioning changes" (Energy: Deep Focus, Time: 15 min). If content is behind cadence, create Action for missing content (Energy: Deep Focus, Time: 15-30 min). If drafts ready for review, create Action "Review [draft name]" (Energy: Quick Win, Time: 5 min).
- **Loop opening for non-trivial actions:** Every Notion Action created that expects a response or has a deadline MUST open a loop:
  ```bash
  python3 q-system/.q-system/loop-tracker.py open action_created "Action title" "Context" "" "ACT-XXX"
  ```
  Skip loop opening for: meeting prep (completed same day), admin tasks, internal-only items. Open loops for: follow-up emails, debrief next steps, intro requests, research with a deadline.

**Step 9.5 - Investor update check:**

Check if it's time to send an investor update by reading `memory/morning-state.md` -> "Investor Update Tracker" section.

- **Milestone triggers (any one = send update):**
  - Design partner signed (LOI or verbal commit)
  - Demo shipped / major product milestone
  - Key hire made
  - Notable press / speaking / award
  - New thesis endorser or CISO validation
  - 30+ days since last update AND at least 1 meaningful thing to report

- **Calendar trigger:** If last update was 30+ days ago, flag it regardless: "It's been [X] days since your last investor update. Anything worth sharing?"

- **If triggered:**
  1. Surface in morning briefing under "INVESTOR UPDATE DUE" with the trigger reason
  2. Create Action: "Draft investor update" (Energy: Deep Focus, Time: 30 min, Type: Other, Priority: This Week)
  3. Suggest: "Run `/q-investor-update` when ready"

- **If not triggered:** Skip silently. No noise.

- **Rules:**
  - Never pressure. Just surface the fact and the trigger.
  - Minimum 2 weeks between updates (don't spam VCs)
  - The update list is everyone in Investor Pipeline DB with status != Passed + anyone in relationships.md tagged "quarterly update list"

**Step 10 — Update Notion Daily Checklists:**
> **HARNESS:** Log as `10_daily_checklists` when done.
- **Daily Actions page** (316bf98c-0529-814c-9d9c-f9940d8758ad): Replace full content with today's actions as to-do checkboxes (`- [ ]`). Organized by: Today Quick Wins → Today Deep Focus → This Week Deep Focus → This Week Quick Wins → Completed Today. Include time estimates and due dates. Pull from both the Actions DB and any new items surfaced in Steps 1-9.
- **Daily Posts page** (316bf98c-0529-8116-81d3-fbf023232749): Replace full content with today's social posts as to-do checkboxes. Include:
  - LinkedIn signal post draft (from Step 4)
  - X signals post draft (from Step 4)
  - X hot take draft (from Step 4 - daily, aim under 100 chars)
  - X behind-the-scenes post (Mon/Wed/Fri from Step 4)
  - X visual post idea (Wed from Step 4 - founder creates visual, caption drafted)
  - LinkedIn thought leadership draft (Tue/Thu from Step 4 continued, if generated)
  - X thought leadership thread (Tue/Thu from Step 4 continued, if generated)
  - Medium article status (Fri: draft ready for review / Sun: publish reminder)
  - LinkedIn comments to post/reply (from Step 3, any threads with new replies, re-engagement opportunities)
  - **ENGAGEMENT HITLIST (from Step 5.9b, COPY-PASTE READY):**
    - LinkedIn comments: each with post link + ready comment text
    - X replies: each with tweet link + ready reply text
    - Connection requests: each with profile link + ready message
    - Reddit comments: each with thread link + ready comment
  - X engagements: 5-7 QTs/replies to target accounts (from Step 2.5 + Step 3)
  - X DMs: 2-3 warm DMs to people who engaged with your posts (from Step 2.5)
  - X replies: respond to any comments on yesterday's posts (from Step 2.5)
  - Any other content to publish (Substack, etc.)
  - Gamma social card link (if generated from Medium article on Fri)
- Both pages use `- [ ]` checkbox syntax so founder can check off items in Notion UI
- Include the actual draft text for posts (not just "generate a post") so founder can copy-paste
- Set "Last updated" date in the page header

**Step 10.5 — Auto-sync Notion (A3, runs silently after Step 10):**
Push all changes from Steps 1-10 to Notion in one batch. This replaces the need to manually run `/q-sync-notion` after mornings:
- New LinkedIn Tracker entries created during Steps 3.8, 5.9, 5.9b
- Contact updates (Last Contact dates, DP Status changes, engagement scores)
- Actions created during Steps 1-9
- Pipeline status changes from Step 3.5
- Content Pipeline entries from Step 4
If Notion MCP is down, skip silently and note "Notion sync deferred" in the handoff note.

**Step 11 — Generate daily schedule JSON + build HTML + open in browser:**

> **GATE CHECK (mandatory before starting Step 11):**
> Re-read morning log from disk. Check Steps 0f through 10 all logged (including `9_notion_push` and `10_daily_checklists`).
> `python3 q-system/.q-system/log-step.py DATE gate-check step_11 true ""`
> If missing steps: `python3 q-system/.q-system/log-step.py DATE gate-check step_11 false "missing_step_ids"` then STOP.
> **Recovery:** If the gate fails, list the missing steps and ask the founder: "These steps didn't run: [list]. Options: (1) I go back and run them now, (2) you tell me to skip them and I'll log them as skipped, (3) we end the session and restart fresh." The founder decides. Claude does NOT self-authorize skipping.

**MANDATORY PRE-CHECK: Re-read `plugins/kipi-core/skills/audhd-executive-function/SKILL.md` before generating.** The daily HTML is the founder's external executive function, not a briefing. Apply all rules.

**HOW IT WORKS:** Claude writes a JSON data file. A build script injects it into a locked-down HTML template. Claude NEVER writes raw HTML.

1. **Read the schema:** `marketing/templates/schedule-data-schema.md` defines the exact JSON format.
2. **Generate JSON:** Write `output/schedule-data-YYYY-MM-DD.json` conforming to the schema.
3. **Build HTML:** Run `python3 marketing/templates/build-schedule.py output/schedule-data-YYYY-MM-DD.json output/daily-schedule-YYYY-MM-DD.html`
4. **Open in browser:** `open output/daily-schedule-YYYY-MM-DD.html` or use Chrome MCP.
5. **Telegram push (if configured):** Send top 3 actions via Telegram MCP.

**JSON content checklist (combine everything from Steps 1-10):**
- `effort`: Yesterday's effort summary (actions taken, not outcomes)
- `callBanners`: Today's meetings from calendar (time, person, link)
- `sections` in this order:
  1. **Quick Wins** (`green`): scheduling replies, short DMs, comments (2-3 min each)
  2. **LinkedIn Engagement** (`blue`): comments from Step 5.9b hitlist
  3. **New Leads** (`yellow`): connection requests + X replies from Step 5.9
  4. **Special Outreach** (`pink`): event outreach, batch campaigns (only when applicable)
  5. **Posts** (`green`/`yellow`): social content drafts (collapsed if published)
  6. **Emails** (`purple`): longer follow-ups, value-adds
  7. **Meeting Prep** (`purple`, collapsed): upcoming call prep with context
  8. **FYI** (`gray`, collapsed): pipeline health, signals, info-only notes

**Engagement hitlist validation:** The hitlist sections MUST mirror Step 5.9b (LinkedIn Comments, X/Twitter Replies, Connection Requests, Reddit Comments). If any type has 0 results, include the section with an info note "None today - [reason]".

**Lead sourcing results:** Qualified prospects from Step 5.9 appear as items with names, titles, post previews, and copy-paste connection requests. Show RESULTS, not search links.

**The template is LOCKED.** All CSS, JS, rendering logic lives in `marketing/templates/daily-schedule-template.html`. Never edit it during morning routine. Never write raw HTML. If a visual bug is found, fix the template in a separate session.

**ACTIONABILITY RULES (ENFORCED - every item in HTML must pass these):**

**Rule A1:** NEVER use cross-references. Never say "Copy-paste from section above" or "See Lead Sourcing section." Every checklist item must contain the actual copy-paste text inline with a Copy button. The user should never scroll or search to find what to send.

**Rule A2:** EVERY checklist item must include the NEXT PHYSICAL ACTION. Not "Follow up with Ryan Hand" but the actual email/DM text ready to copy. Not "Reply to 14 Peaks" but "Hi Cora, Thursday March 12 at 11am ET works great." If a draft can't be pre-written (e.g., "Review Mark's advisory agreement"), say exactly that: "Read the DM first, then respond. No pre-written draft - needs your eyes."

**Rule A3:** EVERY pending Notion Action with Priority "Today" or "This Week" and a Due date <= today must appear in the HTML with a draft message. Query the Actions DB during morning routine and convert every pending action into a copy-paste item.

**Rule A4:** ALL debriefs from the past 48 hours must produce follow-up items in the HTML. If a call happened yesterday, the follow-up email/DM must be in today's Quick Wins with full draft text.

**Rule A5:** Pipeline/temperature dashboards are INFORMATIONAL ONLY. They go in a collapsed section at the bottom. The top of the HTML is ONLY actionable items with copy-paste text. Never put a dashboard item without an attached action and draft.

**Rule A6:** For any risk signal (score dropping, contact cooling), the HTML must include the specific recovery action with draft text. "Phil Venables score 5, dropping" becomes a DM draft. "Costanoa no reply 8 days" becomes a nudge email draft.

**Rule A7:** Items are ordered by friction, lowest first. 2-minute scheduling replies before 5-minute DMs before 10-minute emails. Quick momentum wins first to build dopamine.

**Step 12 - Post-Execution Audit (MANDATORY, runs after Step 11):**

After Step 11 completes (or whenever the morning routine ends, even if ending early):

**12a. Snapshot session-end state checksums:**
Re-read the same key fields from Step 0c:
```bash
python3 q-system/.q-system/log-step.py DATE checksum-end last_calendar_sync "2026-03-14"
python3 q-system/.q-system/log-step.py DATE checksum-end last_gmail_sync "2026-03-14"
python3 q-system/.q-system/log-step.py DATE checksum-end dp_prospect_count "17"
python3 q-system/.q-system/log-step.py DATE checksum-end dp_outreach_count "3"
python3 q-system/.q-system/log-step.py DATE checksum-end decisions_rule_count "17"
python3 q-system/.q-system/log-step.py DATE checksum-end last_publish_date "2026-03-14"
```
The script auto-detects drift between start and end values.

**12b. Mark action cards as delivered:**
```bash
python3 q-system/.q-system/log-step.py DATE deliver-cards
```

**12c. Run the audit harness:**
```bash
python3 q-system/.q-system/audit-morning.py q-system/output/morning-log-DATE.json
```
**Always show the audit output to the founder.** This is not optional.

**12d. Log Step 12 and update morning-state.md:**
```bash
python3 q-system/.q-system/log-step.py DATE 12_audit done "VERDICT - X/Y steps"
```
Update `memory/morning-state.md` with today's sync dates, audit verdict, and any open items.

**12e. Recovery (if audit verdict is not COMPLETE):**
Show the founder the full audit output. Ask: "The routine completed at X%. Here are the gaps: [list]. Options: (1) I go back and run the missing steps now, (2) we accept today's run as-is and fix it tomorrow, (3) we start a fresh session." The founder decides.

---

**Step 3.8 - LinkedIn DM + Connection Accept check (via Chrome):**
> **HARNESS:** Log as `3.8_dm_check`. Result = DM reply count + accept count. Also: for each DM reply or accept detected, add a verification entry to `verification_queue` confirming the detection. This step ALSO verifies yesterday's action cards of type `linkedin_comment`, `linkedin_dm`, `connection_request` by checking if they actually appear in the founder's activity.

This step auto-detects DM replies and connection accepts so the founder never needs to report them manually. It wires directly into the Relationship Progression Engine.

- **Chrome browser** (`mcp__claude-in-chrome__*`):

  **Part A - DM check (10-day lookback):**
  Navigate to `linkedin.com/messaging/` in the founder's logged-in browser session. Scroll to load threads from the last 10 days. Read all visible DM threads.
  - **Extract for each thread:** sender name, latest message text (not just snippet - read the full last message), who sent last (them or you), whether unread, timestamp
  - **Cross-reference Notion Contacts DB:** Match sender names. For known contacts: pull DP Status, relationship stage, last interaction, what was discussed.
  - **Cross-reference LinkedIn Tracker DB:** Check for matching Outreach DM entries with Status = "Sent". If the other person sent the last message and we have a "Sent" entry, this is a REPLY - auto-detected.

  **Part B - Connection Accept detection:**
  Navigate to `linkedin.com/mynetwork/invitation-manager/sent/` (or use `linkedin.com/mynetwork/`). Check for recently accepted connection requests.
  - **Extract:** Names of people who accepted in the last 10 days
  - **Cross-reference LinkedIn Tracker DB:** Match against Connection Request entries with Status = "Sent". Any match = auto-detected accept.

  **Part C - Pending Connection Requests:**
  On the same page, check for pending (not yet accepted) connection requests.
  - **Cross-reference LinkedIn Tracker:** Flag any that are 10+ days old with no response (for timeout handling in Step 5.9b)

  **Part D1 - Debrief next-step loop closer:**
  When a debrief_next_step loop exists and the founder has now SENT the follow-up (detected as a new outbound DM/email in this step), close the debrief loop and open the appropriate new loop:
  ```bash
  # If the debrief said "send deck to Bob" and we detect the email was sent:
  python3 q-system/.q-system/loop-tracker.py close <debrief_loop_id> "next step completed - email sent" "auto_step_3.8"
  # The email_sent loop was already opened by Step 9 or 5.85
  ```
  Also: during Step 0b action card confirmation, if the founder confirms a card that matches a debrief_next_step loop's action_card_id, auto-close:
  ```bash
  python3 q-system/.q-system/loop-tracker.py close <loop_id> "action card confirmed by founder" "founder"
  ```

  **Part D - Outbound action detection (auto-detect what the founder DID):**
  Detect outbound actions the founder took since last check so they never need to manually report "commented on X" or "sent DM to Y":
  - **Comments posted:** Check `linkedin.com/in/[founder-slug]/recent-activity/comments/` for comments posted in the last 48h. Cross-ref LinkedIn Tracker: if the comment target is a known Contact AND no Comment entry exists for that post, auto-log it. This replaces the founder saying "commented on [name]'s post."
  - **DMs sent:** In the messaging threads from Part A, detect threads where the founder sent the last message AND no matching "Sent" LinkedIn Tracker entry exists. Auto-log as Outreach DM with Status: Sent. This replaces the founder saying "sent DM to [name]."
  - **Connection requests sent:** Check `linkedin.com/mynetwork/invitation-manager/sent/` for recently sent requests (last 48h). Cross-ref LinkedIn Tracker: if no matching Connection Request entry exists, auto-log it. This replaces the founder saying "sent connection request to [name]."
  - **Auto-advance relationship stages:** After logging, check if the action triggers a stage advancement (e.g., 2+ comments logged = ready for Connect stage, DM sent = advance to First DM stage).

- **LOOP AUTO-CLOSE (Step 3.8):** After detecting replies and accepts, cross-reference against `output/open-loops.json`:
  ```bash
  # For each DM reply detected:
  python3 q-system/.q-system/loop-tracker.py close <loop_id> "DM reply detected" "auto_step_3.8"
  # For each connection accept detected:
  python3 q-system/.q-system/loop-tracker.py close <loop_id> "connection accepted" "auto_step_3.8"
  # For dp_offer_sent loops where target replied via DM:
  python3 q-system/.q-system/loop-tracker.py close <loop_id> "DP replied to offer" "auto_step_3.8"
  ```
  Match by target name. If a loop target name matches a DM reply sender or connection accepter, close it.

- **Auto-actions on detection (NO founder input needed):**

  **When a DM REPLY is detected:**
  1. Update LinkedIn Tracker entry: Status "Sent" -> "Responded", Response Summary = their reply text
  2. Update Contact: Last Contact = today, Status = "Warm" or "Active" (if was Cooling/Cold)
  3. Generate copy-paste reply suggestion based on:
     - What they said (full message text)
     - Their profile/role/what they care about (from Contact)
     - Current relationship stage (aim toward next stage)
     - {{YOUR_PRODUCT}} positioning rules (no pitch unless they ask)
  4. Add to morning briefing hitlist under "REPLIES TO CONTINUE" with their message + suggested reply
  5. If reply indicates interest in a call/demo: flag as HIGH PRIORITY, generate scheduling message

  **When a CONNECTION ACCEPT is detected:**
  1. Update LinkedIn Tracker entry: Status "Sent" -> "Responded"
  2. Update Contact: Last Contact = today
  3. Advance relationship to Stage 3 (First DM)
  4. Generate copy-paste first DM:
     - Reference their recent posts or the topic from the connection request
     - Ask a genuine question about their work/pain
     - No pitch, value-first
     - Include UTM-tagged link only if sharing a relevant signal
  5. Add to morning briefing hitlist under "FOLLOW-UP DMs DUE" with the ready DM
  6. Set Follow-up Date: 7 days out (for DM timeout check)

  **When a DM needs a reply (they sent last, not outreach-related):**
  1. Generate copy-paste reply suggestion
  2. Add to morning briefing under "DMs NEEDING REPLY"

- **Response detection for auto-close:** If a DM reply is detected from a prospect who has DP Status = "Outreach Sent", that counts as a response - do NOT auto-close that contact in Step 3.5. Reset the auto-close clock.

- **Do NOT flag:** LinkedIn spam, recruiter messages, generic connection requests with no message, InMail from vendors

- **Output appended to morning briefing:**
  ```
  💬 LINKEDIN DMs + CONNECTIONS (last 10 days, auto-detected)

  🆕 CONNECTION ACCEPTS (auto-detected, DMs ready):
  [Name] accepted [X days ago]
  💬 Copy-paste first DM:
  "[ready DM, value-first, genuine question]"
  ⏱️ 3 min | Quick Win

  💬 DM REPLIES (auto-detected, responses ready):
  [Name] said: "[their full message]"
  💬 Copy-paste reply:
  "[suggested reply, advances relationship]"
  ⏱️ 5 min | Quick Win

  📩 DMs NEEDING REPLY (they sent last):
  [Name]: "[message snippet]"
  💬 Copy-paste reply:
  "[suggested reply]"
  ⏱️ 5 min | Quick Win

  ⏳ PENDING CONNECTION REQUESTS:
  [X] pending | [Y] older than 10 days (may not accept)

  📊 SUMMARY: [X] new accepts, [Y] DM replies, [Z] needing reply
  ```

- **Create Actions:** For each DM needing a reply or new accept needing a first DM, create a Notion Action (Energy: Quick Win, Time: 3-5 min, Type: LinkedIn, Priority: Today)

**MCP tools used:**
- Google Calendar: `mcp__claude_ai_Google_Calendar__gcal_list_events`
- Gmail: `mcp__claude_ai_Gmail__gmail_search_messages`, `mcp__claude_ai_Gmail__gmail_read_message`
- Notion: `mcp__claude_ai_Notion__notion-search`, `mcp__claude_ai_Notion__notion-fetch`, `mcp__claude_ai_Notion__notion-update-page`, `mcp__claude_ai_Notion__notion-create-pages`
- Apify (X/Twitter ONLY): `mcp__apify__*` - `apidojo~tweet-scraper` for X activity and lead sourcing. NOT for LinkedIn, Reddit, Medium, or Substack.
- Chrome (LinkedIn primary + interactive): `mcp__claude-in-chrome__*` - Use for: ALL LinkedIn scraping (profiles, posts, DMs, comments, search), posting comments/replies, checking notifications, Google Analytics, visual content review.
- Reddit MCP: `mcp__reddit__*` - search, search_subreddit, get_post, get_subreddit_posts, get_user, get_user_posts. No auth needed. Full content + engagement data.
- RSS feeds via WebFetch: Medium (`medium.com/feed/` endpoints), Substack (`*.substack.com/feed`). Primary data source for Medium and Substack content.
- VC Pipeline Manager: `http://localhost:5050/api/pipeline` (GET) - Returns full VC pipeline with 66+ contacts, warm intro paths, tiers, statuses. Use `WebFetch` to pull. Data source for warm intro matching (Step 1.5) and cross-referencing connectors. App at `http://localhost:5050/`.
- NotebookLM: `mcp__notebooklm__add_notebook`, `mcp__notebooklm__ask_question`, `mcp__notebooklm__search_notebooks`
- Signals: `WebFetch` on `https://{{YOUR_DOMAIN}}/signals`
- Google Analytics (Mondays): `mcp__claude-in-chrome__*` on `analytics.google.com` (authuser=2, property a385692819p526076376)
- Gamma: `mcp__gamma__generate_gamma`, `mcp__gamma__get_gamma_generation`

---

### Content intelligence (`/q-content-intel`):

> Scrape your own content across all platforms. Analyze what works vs. what doesn't. Build a data-driven content scoring model.

**Full run (weekly, or on demand):**

1. **Scrape all platforms** using Chrome (LinkedIn), Reddit MCP, Apify (X only), and RSS feeds (Medium, Substack):
   - **LinkedIn:** Navigate to founder's profile via Chrome. Pull last 30 days of posts. Extract: text, impressions, likes, comments, reposts, date/time posted.
   - **X/Twitter:** Apify `apidojo~tweet-scraper` on {{YOUR_X_HANDLE}}. Pull last 30 days. Extract: text, impressions, likes, retweets, replies, quotes, date/time.
   - **Medium:** Pass 1: `WebFetch(url="https://medium.com/feed/@{{YOUR_MEDIUM_HANDLE}}", prompt="Extract all articles: title, URL, author, date, content text. Numbered list.")`. Pass 2: Navigate to each article via Chrome for claps, responses, read ratio (RSS has no engagement metrics).
   - **Reddit:** Use Reddit MCP `mcp__reddit__get_user_posts` with `username={{YOUR_REDDIT_USERNAME}}`, `limit=20`. Returns posts with title, score, comments, subreddit, full content. No two-pass needed. Pull last 30 days.
   - **Substack:** `WebFetch(url="https://{{YOUR_SUBSTACK}}.substack.com/feed", prompt="Extract all posts: title, URL, date, content text. Numbered list.")`. Open rate requires Substack dashboard via Chrome.

2. **Normalize and rank:**
   - Calculate engagement rate per post: (likes + comments + reposts) / impressions
   - Rank all posts by engagement rate across each platform
   - Tag each post with its content theme (1-8 from `marketing/content-themes.md`)
   - Tag each post with format: signals, thought leadership, hot take, BTS, thread, article, comment

3. **Pattern extraction:**
   - **Top 20% posts:** What language, format, topic, length, time-of-day do they share?
   - **Bottom 20% posts:** What patterns do they share? What to avoid?
   - **Theme analysis:** Which themes perform best on which platforms?
   - **Format analysis:** Which format (signals vs TL vs hot take vs thread) gets most engagement per platform?
   - **Timing analysis:** What day/time combinations produce highest engagement?
   - **Hook analysis:** Extract first lines of top performers. What makes them stop the scroll?
   - **Language analysis:** Extract specific phrases, framings, and words that appear in top performers but not bottom performers.

4. **Update `canonical/content-intelligence.md`:**
   - Refresh all Performance Baselines tables
   - Add/update entries in "What Works" and "What Doesn't Work"
   - Update Theme Performance table with actual data
   - Update Content Scoring Model criteria based on patterns found
   - Add Weekly Intel Log entry with raw observations

5. **Generate recommendations:**
   ```
   CONTENT INTELLIGENCE REPORT

   DATA PULLED:
   LinkedIn: [X] posts scraped
   X: [X] tweets scraped
   Medium: [X] articles scraped
   Reddit: [X] posts scraped
   Substack: [X] newsletters scraped

   TOP PERFORMERS (by engagement rate):
   1. [platform] - [post summary] - [rate]
   2. [platform] - [post summary] - [rate]
   3. [platform] - [post summary] - [rate]

   BOTTOM PERFORMERS:
   1. [platform] - [post summary] - [rate]
   2. [platform] - [post summary] - [rate]
   3. [platform] - [post summary] - [rate]

   PATTERNS FOUND:
   - Works: [specific pattern with evidence]
   - Works: [specific pattern with evidence]
   - Doesn't work: [specific pattern with evidence]

   LANGUAGE:
   - Reuse: "[exact phrase]" (appeared in X top posts)
   - Avoid: "[exact phrase]" (appeared in X bottom posts)

   THEME RANKING (best to worst):
   [ordered list with engagement rates]

   RECOMMENDATIONS FOR NEXT WEEK:
   1. [specific, actionable change]
   2. [specific, actionable change]
   3. [specific, actionable change]
   ```

6. **Save report** to `output/content-intel/content-intel-YYYY-MM-DD.md`

**Quick score (on demand, for any draft):**

Run `/q-content-intel score` with a draft post. Scores it 1-5 on hook strength, pattern match, platform fit, timing, and novelty using current `canonical/content-intelligence.md` data. Returns pass/revise/rethink recommendation.

**Cost estimate:** Apify ~$0.50 per run (X/Twitter only). Reddit MCP, RSS feeds, and Chrome are free (included in Claude Max plan).

---

### Investor update (`/q-investor-update`):

> Milestone-triggered investor update email. Drafts a concise, high-signal update for the full VC list. Not a newsletter - a founder update that makes VCs feel like insiders.

**When to run:** When `/q-morning` Step 9.5 flags an update is due, or on demand after a milestone.

**Workflow:**

1. **Pull current state:**
   - Read Investor Pipeline DB (DB fd92016f-7890-40c3-abe9-154c864e05b3) for all VCs with status != Passed
   - Read `my-project/relationships.md` for anyone tagged "quarterly update list"
   - Read `my-project/progress.md` for recent milestones since last update
   - Read `memory/morning-state.md` -> "Investor Update Tracker" for last update date and content

2. **Identify what's new since last update:**
   - New design partners or LOIs
   - Product milestones (features shipped, demo improvements, code metrics)
   - New thesis endorsers or CISO validations
   - Notable conversations (only share if the person would be comfortable being named)
   - Content/community traction (if meaningful - LinkedIn engagement, Medium reads, speaking invites)
   - Team updates (hires, advisors)
   - Upcoming events (RSA, conferences, pitch competitions)

3. **Draft the update email:**
   - **Template:** Read `marketing/templates/investor-update.md` for structure and rules.
   - **Format:** Plain text email. No HTML, no fancy formatting. Founder-to-investor voice.
   - **Structure:**
     ```
     Subject: {{YOUR_PRODUCT}} Update - [Month] [Year] - [1 headline]

     Hi [first name],

     Quick update on {{YOUR_PRODUCT}} since we last talked.

     HIGHLIGHT (1 sentence - the single biggest thing)
     [The one thing that moves the needle most]

     PRODUCT
     - [2-3 bullets, concrete, no fluff]

     TRACTION
     - [Design partners, conversations, pipeline numbers]

     WHAT'S NEXT
     - [2-3 bullets on immediate priorities]

     ASK (optional - only if there's a specific, low-effort ask)
     - [Intro to a specific person, feedback on a specific thing]

     Thanks for following along.
     Assaf
     ```
   - **Rules:**
     - Under 300 words. VCs scan, they don't read.
     - Lead with the strongest proof point, not vision.
     - No "we're excited to announce" or "thrilled to share" - just state the fact.
     - Numbers over adjectives. "3 design partners" not "growing traction."
     - The ASK must be specific and low-effort. "Would you intro me to [Name] at [Company]?" not "Let me know if you know anyone."
     - Personalize the ASK per VC based on their portfolio/network (batch of 3-4 variants max).

4. **Generate variants:**
   - **Active pipeline VCs** (status: Follow-up, First Meeting): Include ASK tailored to their portfolio.
   - **Thesis nod VCs** (status: First Meeting done, no next step): Standard update, no ASK. Let the traction speak.
   - **Warm connectors** (people who offered intros): Include specific intro ASK if relevant.
   - **BCC list** (everyone else on the update list): Standard update, generic sign-off.

5. **Save and track:**
   - Save draft to `output/investor-updates/investor-update-YYYY-MM-DD.md`
   - Include the recipient list with variant assignments
   - Update `memory/morning-state.md` -> "Investor Update Tracker" with date and summary
   - Create Action: "Review and send investor update" (Energy: Deep Focus, Time: 15 min, Priority: Today)

6. **Output:**
   ```
   INVESTOR UPDATE DRAFT

   Recipients: [X] active pipeline + [Y] thesis nod + [Z] connectors = [total]

   STANDARD VERSION:
   [full email text]

   VARIANT A (active pipeline - [names]):
   [ASK paragraph customized]

   VARIANT B (connectors - [names]):
   [ASK paragraph customized]

   Saved to: output/investor-updates/investor-update-YYYY-MM-DD.md
   ```

**Post-send tracking:**
After founder confirms the update was sent, update:
- `memory/morning-state.md` -> "Investor Update Tracker" -> Last sent date
- Notion Interactions DB: Create one entry "Investor Update - [Month] [Year]" (Type: Email, Source: Q Debrief)
- Any VC who replies: create individual Interaction entries and update relationship status

---

### Marketing commands (`/q-market-*`):

**`/q-market-plan` — Weekly content planning (run Monday or start of week):**

1. Read `marketing/editorial-calendar.md` for this week's theme assignments
2. Read `marketing/content-themes.md` for theme details and canonical sources
3. Check `memory/marketing-state.md` for last week's publish log (what landed, what was skipped)
4. Check recent debriefs in `my-project/progress.md` for fresh insights that map to themes
5. **Read `canonical/market-intelligence.md`** for recent market signals. Use buyer language from the Problem Language section when writing about matching themes. Prioritize topics that align with Category Signals or market patterns detected in the last 2 weeks. If the market is talking about something we have a theme for, that topic gets priority this week.
6. Assign specific topics to each content slot:
   - Tue LinkedIn TL: [theme] + [specific angle based on recent signals, debriefs, or calendar]
   - Thu LinkedIn TL: [theme] + [specific angle]
   - Fri Medium: [theme] + [specific deep dive topic]
   - Sun Substack: [theme] + [newsletter angle - can repurpose/expand Medium article or be original]
6. Check for upcoming meetings (from Calendar) — auto-queue one-pagers and meeting decks
7. Update `marketing/editorial-calendar.md` with assigned topics
8. Create Notion Editorial Calendar DB entries for each planned piece
9. Create Notion Content Pipeline DB entries (Status: Idea) for each
10. Output weekly plan:
    ```
    📅 CONTENT PLAN (week of [date])
    Cycle week: [1-4]

    Tue: [Theme] — [Topic] (LinkedIn TL + carousel)
    Thu: [Theme] — [Topic] (LinkedIn TL + carousel)
    Fri: [Theme] — [Topic] (Medium draft + header image)
    Sat: Substack newsletter draft (can repurpose/expand Medium or be original)
    Sun: Medium publish + Substack publish

    Daily: Signals posts (LinkedIn + X) with social card visuals

    Meeting prep:
    - [Name] — one-pager queued
    - [Name] — custom deck queued (Gamma)

    Stale assets to refresh: [list or "None"]
    ```

**`/q-market-create [type] [topic]` — Content generation:**

Supported types and their templates:

| Type | Template | NotebookLM | Gamma Visual | Output Dir |
|------|----------|-----------|-------------|-----------|
| `linkedin` | linkedin-thought-leadership.md | If theme benefits | Yes (social card or carousel) | output/marketing/linkedin/ |
| `x` | x-thought-leadership.md | If theme benefits | Yes (social card) | output/marketing/x/ |
| `medium` | medium-article.md | Yes (primary) | Yes (header image + social card) | output/marketing/medium/ |
| `substack` | substack-newsletter.md | Yes (primary) | Yes (newsletter header) | output/marketing/substack/ |
| `one-pager` | one-pager.md | Yes (industry context) | Yes (document format) | output/marketing/one-pagers/ |
| `outreach` | outreach-email.md | No | No | output/marketing/outreach/ |
| `deck` | slide-deck-brief.md | Optional | Yes (presentation format) | output/marketing/decks/ |
| `follow-up` | follow-up-email.md | No | No | output/marketing/outreach/ |
| `reddit` | reddit-post.md | No | No | output/marketing/reddit/ |
| `investor-update` | investor-update.md | No | No | output/investor-updates/ |

Workflow for each type:
1. Read the corresponding template from `marketing/templates/`
2. **Read `canonical/content-intelligence.md`** for current performance patterns. Use high-performing language, formats, and hooks. Avoid low-performing patterns. This step is MANDATORY for linkedin, x, and medium types.
2.1. **Read `canonical/market-intelligence.md`** for buyer language and market signals. When writing about a topic, use the verbatim problem language from practitioners instead of our marketing copy where possible. If the market-intelligence file has relevant category signals or objection previews, address them in the content. This step is MANDATORY for linkedin, x, medium, and outreach types.
2.5. **Read `marketing/brand-kit.html`** for visual identity (colors, fonts, components, layout patterns). This step is MANDATORY for one-pager, deck, and any HTML/visual output. For linkedin, x, and medium types, reference the brand kit when generating any accompanying visual assets (social cards, carousels, banners). Use the CSS variables (--k- prefix), type scale, component patterns, and CNS color naming from the kit.
3. Follow template's pre-generation steps (canonical sources, NotebookLM queries, CRM lookup)
4. Generate content following template structure, informed by content intelligence patterns
5. **Generate Gamma visual (MANDATORY for all content types except outreach/follow-up/reddit/investor-update):**
   - **linkedin:** Call `mcp__gamma__generate_gamma` with format "social", inputText = post summary + key stat/quote. For thought leadership, generate a carousel (format "presentation", 3-5 slides, one insight per slide). Save Gamma URL + export links alongside the post file.
   - **x:** Call `mcp__gamma__generate_gamma` with format "social", inputText = hot take or key stat. Single image card. Save URL + exports.
   - **medium:** Call `mcp__gamma__generate_gamma` twice: (1) format "social" for article header image (title + key visual), (2) format "social" for LinkedIn/X sharing card. Save both URLs.
   - **substack:** Call `mcp__gamma__generate_gamma` with format "social", inputText = newsletter title + key insight. Newsletter header image. Save URL + exports.
   - **deck:** Call `mcp__gamma__generate_gamma` with format "presentation" and inputText built from `slide-deck-brief.md`. Then `mcp__gamma__get_gamma_generation` for URL + exports.
   - **one-pager:** Call `mcp__gamma__generate_gamma` with format "document" and inputText built from `one-pager.md`. Then `mcp__gamma__get_gamma_generation`.
   - **Gamma visual prompt rules:** Always reference `marketing/brand-kit.html` colors and style in the prompt. Include "Use dark background (#0a0a12), indigo accent (#6366f1), green for data (#34d399). Instrument Serif for headlines, DM Sans for body." Keep text minimal on visuals. Stats and quotes are the anchors.
6. Run `marketing/content-guardrails.md` checks automatically
9. **Score against content intelligence** (for linkedin, x, medium): Run the Content Scoring Model from `canonical/content-intelligence.md`. Include score in output. If score < 3, flag for revision with specific suggestions based on what works.
10. Save to appropriate output directory
11. Create Content Pipeline DB entry (Status: Drafted)
12. Output: draft text + guardrail result + content intelligence score + file path (+ Gamma URL/exports if applicable)

**`/q-market-review [file]` — Content validation:**

1. Read the content file
2. Run ALL checks from `marketing/content-guardrails.md`:
   - Misclassification check
   - Language check (banned words, emdashes)
   - Overclaiming check (all 14 RULEs)
   - Decision compliance check
   - Voice check (channel-appropriate)
   - Channel-specific checks
3. Output PASS/FAIL with specific issues and fix suggestions
4. If PASS: Update Content Pipeline DB entry to Status: Reviewed, Guardrails Passed: Yes

**`/q-market-publish [file]` — Mark content published:**

1. Read the content file
2. Verify guardrails have passed (check Content Pipeline DB or re-run if needed)
3. Update Content Pipeline DB: Status → Published, Published Date → today
4. Update Editorial Calendar DB if applicable: Status → Published
5. Update `memory/marketing-state.md`:
   - Add to Publish Log
   - Update Content Cadence for current week
   - Increment Pipeline Summary counts
6. Output confirmation with publish details

**`/q-market-assets` — Asset refresh:**

1. Read `memory/marketing-state.md` Asset Freshness table
2. For each asset, check source file modification dates:
   - Read each source file's content and compare against asset content
   - If source has material changes since last refresh → mark stale
3. For stale assets: regenerate from current canonical sources
4. Check Gamma Deck Tracker: compare canonical file dates against deck generation dates
   - If positioning changes since deck generation → flag deck for re-generation
   - Optionally: generate new Gamma deck via `mcp__gamma__generate_gamma`
5. Update `memory/marketing-state.md` with new refresh dates
6. Update Asset Library DB in Notion
7. Output:
   ```
   ASSET REFRESH REPORT

   REFRESHED:
   - [asset name] — source changed: [what changed]

   CURRENT (no changes needed):
   - [asset name]

   GAMMA DECKS:
   - [deck name] — [Current / Needs Review / Re-generated]

   All assets: [X current / Y refreshed / Z flagged]
   ```

**`/q-market-status` — Marketing snapshot:**

1. Read `memory/marketing-state.md`
2. Pull Content Pipeline DB counts from Notion
3. Output:
   ```
   📣 MARKETING STATUS

   PIPELINE:
   Ideas: [X] | Drafted: [X] | Reviewed: [X] | Published: [X] | Killed: [X]

   THIS WEEK'S CADENCE:
   Signals: [X/5] | TL Posts: [X/2] | Medium: [status]

   ASSET HEALTH:
   [X/5] current | [list stale if any]

   GAMMA DECKS:
   [deck name] — [status] — [url]

   RECENT PUBLISHES:
   [last 5 from publish log]

   STALE DRAFTS:
   [list or "None"]
   ```

---

### Marketing system cross-references:

**Files:**
- System overview: `marketing/README.md`
- Voice rules: `marketing/brand-voice.md`
- Theme rotation: `marketing/content-themes.md`
- Editorial calendar: `marketing/editorial-calendar.md`
- Guardrails: `marketing/content-guardrails.md`
- Templates: `marketing/templates/*.md`
- Assets: `marketing/assets/*.md`
- State: `memory/marketing-state.md`

**Notion databases:**
- Content Pipeline DB: (created by /q-market-plan first run)
- Editorial Calendar DB: (created by /q-market-plan first run)
- Asset Library DB: (created by /q-market-assets first run)
- Parent page: 314bf98c-0529-81bb-a576-d5982475fd2d (CRM parent)

**NotebookLM:**
- Marketing Knowledge Base notebook: bb6ae0cb-0677-4611-84ab-dde086461668

**Gamma MCP:**
- `mcp__gamma__generate_gamma` — generate presentations, documents, social cards
- `mcp__gamma__get_gamma_generation` — retrieve URLs and export links
- Existing deck: https://gamma.app/docs/sqm26tt7e54f8kj (Short Deck v3)
- Edit queue: `output/gamma-v3-edit-queue.md`

---

### `/q-checkpoint` — Auto-save canonical state:

> Runs automatically inside `/q-end`. Can also be invoked manually at any time.

1. **Snapshot canonical file state:**
   - List all canonical files (`canonical/*.md`, `my-project/*.md`, `CLAUDE.md`) with their current line counts
   - Compare against last checkpoint entry in `my-project/progress.md` to identify what changed

2. **Verify consistency:**
   - Run decision compliance check (same as `/q-morning` Step 6): grep all active RULEs from `canonical/decisions.md` across canonical files
   - Flag any violations (but do NOT block the checkpoint)

3. **Log to `my-project/progress.md`:**
   - Add a new entry with today's date, mode summary, and all canonical changes made this session
   - List files changed, key insights, and next steps

4. **Update `memory/morning-state.md`:**
   - Set `Last checkpoint: YYYY-MM-DD HH:MM` in a new "Checkpoint Tracking" section
   - This timestamp is what `/q-morning` Step 7.5 uses to detect drift

5. **Output:**
   ```
   CHECKPOINT SAVED
   Files changed this session: [list]
   Decision compliance: [PASS or violations]
   Logged to: my-project/progress.md
   Last checkpoint: [timestamp]
   ```

### `/q-end` — End session (auto-checkpoints first):

1. **Run `/q-checkpoint`** (Steps 1-4 above). This ensures state is always saved even if the founder forgets.

2. **Session summary:**
   - List all canonical files modified during this session
   - List all Notion records created/updated
   - List any new RULEs added to `decisions.md`
   - Note any unresolved items (flagged as {{UNVALIDATED}} or {{NEEDS_FOUNDER_INPUT}})

3. **Output:**
   ```
   SESSION COMPLETE

   CHANGES:
   - [file]: [what changed]
   - [file]: [what changed]

   NOTION UPDATES:
   - [X] contacts created/updated
   - [X] interactions logged
   - [X] actions created

   OPEN ITEMS:
   - [any unresolved markers or pending decisions]

   Checkpoint saved. You can close this session.
   ```

---

### Evening wrap (`/q-wrap`):

> 10-minute end-of-day system health check. Closes open loops, previews tomorrow.

Use the `/q-wrap` skill for the full workflow (5 steps).

**Quick summary:**
1. **Effort log** (2 min): Count actions taken today from Notion. Track effort, not outcomes.
2. **Unfinished actions triage** (3 min): What carries over? What's stale? No guilt.
3. **Debrief check** (1 min): Any meetings without debriefs?
4. **Canonical drift check** (2 min): Any insights not yet in canonical files?
5. **Tomorrow preview** (2 min): Calendar + prep status for tomorrow's meetings.

**After wrap (all automatic, founder does nothing):**
- Auto-checkpoint (update morning-state.md)
- Promote working memory to weekly if still relevant (`memory/working/` -> `memory/weekly/`)
- Clean up stale working memory (>48h old files)
- **Auto-run `/q-handoff`** to generate session handoff note. The founder NEVER needs to run /q-handoff separately after /q-wrap. It's always chained automatically.

**Telegram push (if configured):**
After the wrap completes, send the top 3 actions for tomorrow via Telegram MCP. Format:
```
Tomorrow's top 3:
1. [action] (Quick Win, 5 min)
2. [action] (Quick Win, 10 min)
3. [action] (Deep Focus, 30 min)
```
This gives the founder a preview on their phone so they wake up knowing what's first.

---

### Session handoff (`/q-handoff`):

> Formal session-end message for the next session. Ensures continuity across context window resets.

Use the `/q-handoff` skill for the full spec.

**When to trigger:**
- User says "done", "stopping", "wrapping up"
- Context window >80% consumed
- After `/q-wrap` completes
- Before expected context compaction

**Saves to:** `memory/last-handoff.md` (overwritten each time)

**Next session reads this in Step 0c** to pick up where the last session left off.

---

### Reality check (`/q-reality-check`):

> Challenger mode. Stress-tests current positioning, claims, and assumptions against evidence.

**Purpose:** Prevent confirmation bias. The system normally optimizes for the founder's positioning. This command temporarily reverses that and argues AGAINST current assumptions.

**Workflow:**

1. **Read all canonical files** to understand current claims and positioning.

2. **Read `canonical/market-intelligence.md`** and cross-reference against positioning. Specifically check:
   - Does the Problem Language section describe the pain the way WE describe it? If not, are we using the wrong words?
   - Do Category Signals suggest the market wants what we're building, or something adjacent?
   - Do Objection Previews reveal concerns we haven't addressed in `canonical/objections.md`?
   - Does the Narrative Validation Log show a pattern of confirms or contradicts?
   - Are there Competitive Intel entries that change our differentiation story?

3. **Challenge each claim category:**

   **Positioning challenges:**
   - "You say {{YOUR_PRODUCT}} is {{YOUR_METAPHOR}}. What if enterprises already have this and you're solving a problem that doesn't exist at your target scale?"
   - "You say detection is one of seven artifact types. Can you name a customer who cares about artifact type #5 (email transport rules)?"
   - "What if the 'governance wedge' only matters to compliance-heavy industries and the broader market doesn't care?"

   **Traction challenges:**
   - "You have X design partners. How many have actually used the product vs. just said 'interesting'?"
   - "Your outreach reply rate is X%. Is that because of personalization or because you're contacting the wrong people?"
   - "What's the fastest path to $100K ARR and does your current pipeline support it?"

   **Market challenges:**
   - "Name 3 companies that tried to build this category and failed. Why did they fail? Why won't you?"
   - "If this problem is real, why hasn't Splunk/Palo Alto/CrowdStrike built it?"
   - "What happens to your value prop when LLMs get 10x cheaper and every tool can 'learn'?"

3. **For each challenge:**
   - State the challenge clearly
   - Rate current evidence: STRONG (data backs it), MODERATE (anecdotal), WEAK (assumption only)
   - If WEAK: flag for validation with a specific experiment
   - If MODERATE: suggest how to strengthen to STRONG

4. **Output:**
   ```
   REALITY CHECK - [date]

   STRONG (backed by evidence):
   - [claim] - evidence: [specific data point]

   MODERATE (anecdotal, needs strengthening):
   - [claim] - evidence: [what we have] - to strengthen: [what to do]

   WEAK (assumption, needs validation):
   - [claim] - experiment: [specific test to run]

   BLIND SPOTS:
   - [things we haven't considered or tested]

   HARDEST QUESTION A VC WILL ASK:
   "[the one question we can't answer yet]"
   ```

5. **Rules:**
   - This is NOT hostile. It's Socratic. The goal is to find weak spots before a VC does.
   - No ADHD-unfriendly delivery. Present challenges as puzzles to solve, not failures to fix.
   - Each weak claim gets paired with a concrete, small experiment to validate it.
   - Run monthly or before major VC meetings.

---

### Prediction tracking (outreach):

> Log predictions about outreach outcomes. Track accuracy over time. Calibrate intuition.

**How it works:**

When generating outreach in Step 5.9 or `/q-engage`, the system logs a prediction for each Tier A/B prospect:

```jsonl
{"date":"2026-03-12","prospect":"Jane Doe","channel":"linkedin_dm","prediction":"will_reply","confidence":0.7,"style":"value_drop","outcome":null,"outcome_date":null}
```

**Predictions file:** `memory/working/predictions.jsonl`

**Prediction options:** `will_reply`, `will_accept`, `will_ignore`, `will_engage_later`
**Confidence:** 0.0-1.0

**Outcome tracking:**
- During `/q-morning` Step 3.8 (DM check) and Step 5.8 (scoring), auto-match outcomes to predictions
- Update the `outcome` and `outcome_date` fields when we know what happened

**Monthly calibration (1st of month):**
- Read all predictions from last 30 days
- Calculate accuracy: predictions with confidence >0.7 that came true / total high-confidence predictions
- If accuracy <50%: "Your high-confidence predictions are wrong more than half the time. Consider what signals you're overweighting."
- If accuracy >80%: "Your intuition is well-calibrated. Trust it."
- Promote calibration summary to `memory/monthly/prediction-calibration-YYYY-MM.md`

---

### Outreach A/B testing:

> Tag outreach messages with style codes. Track reply rates per style. Learn what works.

**Style codes (tag every outreach message):**

| Code | Style | Example |
|------|-------|---------|
| `V1` | Value drop (signal share) | "Saw this advisory affecting your stack..." |
| `Q1` | Genuine question | "How does your team handle X?" |
| `P1` | Peer observation | "I built something similar at Meta, curious about your approach" |
| `C1` | Content reference | "Your post about X resonated because..." |
| `W1` | Warm intro follow-up | "Hey, [connector] suggested I reach out because..." |

**Tracking:**
- Every outreach message in Phase 3 (Step 5.9) gets tagged with a style code
- Style code stored in Notion LinkedIn Tracker entry notes field
- During prediction outcome matching, also log the style code

**Monthly analysis (1st of month, after prediction calibration):**
- Group outcomes by style code
- Calculate reply rate per style
- Output: "V1 (value drops): 35% reply rate. Q1 (questions): 20%. P1 (peer): 45%."
- Recommendation: shift toward highest-performing styles
- Save to `memory/monthly/outreach-ab-YYYY-MM.md`

---

### Predict-first prompting (in debriefs):

> Before processing a debrief, predict what the conversation surfaced. Then compare against reality.

**Added to `/q-debrief` workflow, between Steps 2 and 3:**

After reading the person's history (Step 2) but BEFORE the founder describes the conversation (Step 3):

1. **System predicts:**
   - "Based on [person]'s profile and our history, I predict this conversation surfaced:"
   - Top 3 likely objections (from objections.md)
   - Top 3 likely topics (from their LinkedIn + what they care about)
   - Likely relationship outcome (warmer/cooler/same)

2. **Founder describes the conversation.**

3. **System compares:**
   - "Predicted [objection X]. Actual: [what happened]."
   - Log accuracy to `memory/working/predictions.jsonl` (type: `debrief_prediction`)

4. **Value:** Forces the system to develop better models of each contact. Wrong predictions reveal gaps in the canonical files.

---

### Memory management:

> Time-stratified memory architecture. Working/weekly/monthly layers.

**Directory structure:**
```
memory/
├── working/          # Session-scoped, ephemeral (<48h)
├── weekly/           # 7-day rolling window
├── monthly/          # Persistent insights
├── last-handoff.md   # Session handoff note (from /q-handoff)
├── morning-state.md  # Morning routine state tracker
├── marketing-state.md # Marketing system state
└── graph.jsonl       # Entity-relationship knowledge graph
```

**Lifecycle:**
- `working/` files created during sessions. Cleaned during `/q-morning` Step 0a (>48h old) or promoted to `weekly/` during `/q-wrap`.
- `weekly/` files reviewed during Monday `/q-morning`. Promoted to `monthly/` or canonical files if insightful. Archived if consumed.
- `monthly/` files reviewed on 1st of month. Promoted to canonical if proven. Deleted if invalidated.

**Integration with morning routine:**
- Step 0a: Clean stale `working/` files, read `last-handoff.md`
- Monday Step 3.7: Review `weekly/` files, promote or archive
- 1st of month: Review `monthly/` files, promote or archive

---

### Graph knowledge base:

> Structured entity-relationship triples for fast queries across contacts, companies, and concepts.

**File:** `memory/graph.jsonl`

**Format:** One JSON object per line:
```jsonl
{"s":"Edoardo Ermotti","p":"works_at","o":"14 Peaks Capital","t":"2026-03-12"}
{"s":"14 Peaks Capital","p":"invested_in","o":"Cybersecurity","t":"2026-03-12"}
{"s":"Henry Cashin","p":"introduced","o":"Edoardo Ermotti","t":"2026-03-12"}
{"s":"Scattered Spider","p":"exploits","o":"identity_gaps","t":"2026-03-11"}
```

**Triple types:**
- `works_at`, `role_is` - person-company-role
- `introduced`, `knows` - relationship edges
- `invested_in`, `portfolio_includes` - VC-company relationships
- `cares_about`, `posted_about` - interest mapping
- `objected_to`, `resonated_with` - conversation insights
- `exploits`, `targets` - threat intelligence linkage

**When to write:**
- During `/q-debrief`: extract entities and relationships
- During Step 5.9: when discovering new prospects
- During Step 1.5: when mapping warm intro paths
- During `/q-calibrate`: when updating positioning

**When to query:**
- Meeting prep (Step 2): "Who else at [company] have we talked to?"
- Warm intro matching (Step 1.5): "Who knows [prospect]?"
- Content creation (Step 4): "Which contacts care about [topic]?"

**Query via grep:** `grep '"s":"14 Peaks"' memory/graph.jsonl` to find all triples about 14 Peaks.

---

### Inter-skill review gates:

> Before outputting any claim, verify it against canonical files.

**Rule (added to Step 0 of /q-morning and enforced globally):**

Before ANY output that makes a factual claim about {{YOUR_PRODUCT}}, the system MUST:

1. **Check the claim against canonical files:**
   - Capability claims -> `my-project/current-state.md`
   - Market claims -> `canonical/talk-tracks.md` + `my-project/competitive-landscape.md`
   - Proof points -> `marketing/assets/proof-points.md` + `marketing/assets/stats-sheet.md`

2. **If the claim is NOT in a canonical file:**
   - Mark with `{{UNVALIDATED}}` if it's plausible but unproven
   - Mark with `{{NEEDS_PROOF}}` if it's a specific number or metric
   - BLOCK the output if it contradicts a canonical file (e.g., claiming a feature exists when current-state.md says it doesn't)

3. **Applies to:**
   - Outreach messages (Step 5.9 Phase 3)
   - Talk tracks generated by `/q-create`
   - Meeting prep briefs (Step 2)
   - Investor update drafts (`/q-investor-update`)
   - Content drafts (Step 4, `/q-market-create`)

**This is a safety net, not a bottleneck.** Most claims will pass instantly because they come from canonical files. The gate catches hallucinated claims or outdated information.

---

### Fail-fast mode (ENFORCED):

> If anything fails during `/q-morning`, STOP immediately. Do not continue with partial data. Do not silently skip steps.

**Rule: Step 0f is the VERY FIRST thing that runs. Before checkpoint, before debrief detection, before loading canonical files. Nothing else happens until every connection passes.**

**Step 0f - Connection check sequence (run ALL in parallel where possible):**

| # | Server | Exact Test | Pass Criteria | Required for |
|---|--------|-----------|--------------|-------------|
| 1 | Google Calendar | `mcp__claude_ai_Google_Calendar__gcal_list_events` with today's date | Returns events array (even if empty) | Step 1 calendar, meeting prep |
| 2 | Gmail | `mcp__claude_ai_Gmail__gmail_search_messages` with `q: "after:YYYY/M/D"` (yesterday) | Returns messages array | Step 1 email pull, reply detection |
| 3 | Notion (API) | `mcp__claude_ai_Notion__notion-fetch` on Actions DB `0718ee69-d9d0-473d-8182-732d21c60491` with `page_size: 1` | Returns results array | Steps 1-10 (CRM, pipeline, tracker, actions) |
| 4 | Chrome | `mcp__claude-in-chrome__tabs_context_mcp` | Returns tab list | Steps 2, 3, 3.8, 5, 5.5 (LinkedIn, DMs, GA) |
| 5 | Apify (MCP, X only) | Any `mcp__apify__*` tool call | Returns response | Steps 2.5, 5.9 (X/Twitter scraping only) |
| 5b | Apify (REST fallback) | `curl -s "https://api.apify.com/v2/acts?token=$APIFY_TOKEN&limit=1"` via Bash | Returns JSON with `data` array | Fallback if MCP Apify unavailable (X only) |
| 5c | Reddit MCP | `ToolSearch("+reddit")` then `mcp__reddit__search` with query "test" | Returns structured post data | Steps 3.7, 5.9 (Reddit content intel + lead sourcing) |
| 5d | RSS feeds (Medium/Substack) | `WebFetch(url="https://medium.com/feed/tag/cybersecurity", prompt="How many articles?")` | Returns a count or description | Steps 3.7, 5.9 (Medium content intel + lead sourcing) |
| 6 | VC Pipeline API | `curl -s http://localhost:5050/api/pipeline` via Bash | Returns JSON pipeline data | Steps 1, 1.5 (warm intro matching) |
| 7 | NotebookLM | `mcp__notebooklm__list_notebooks` | Returns notebook list | Research grounding (Step 2) |

**Output format (ALWAYS shown, even when all pass):**

```
CONNECTION CHECK (Step 0f)

[PASS] Google Calendar - events loaded
[PASS] Gmail - messages loaded
[PASS] Notion API - Actions DB accessible
[PASS] Chrome - browser connected
[PASS] Apify MCP - X/Twitter tools loaded
[PASS] Reddit MCP - search working
[PASS] RSS feeds - Medium/Substack reachable
[PASS] VC Pipeline API - pipeline data loaded
[PASS] NotebookLM - notebooks accessible

All 8 connections OK. Proceeding to Step 0a.
```

**If ANY fails:**

```
MORNING ROUTINE HALTED - CONNECTION CHECK FAILED

[PASS] Google Calendar - events loaded
[PASS] Gmail - messages loaded
[FAIL] Notion API - Error: "Could not find property..."
[SKIP] Chrome - not tested (halted)
[SKIP] Apify (X only) - not tested (halted)
[SKIP] Reddit MCP - not tested (halted)
[SKIP] RSS feeds - not tested (halted)
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

If the founder says proceed, note the skipped steps in the briefing output. Critical servers (Calendar, Gmail, Notion, Chrome) have NO degraded mode - they halt the routine. Apify failure only blocks X/Twitter scraping (Steps 2.5, 5.9 X portion) and has Chrome fallback. Reddit MCP failure only blocks Reddit in Steps 3.7 and 5.9 (no Chrome fallback - skip Reddit). RSS failure only blocks Medium/Substack in Steps 3.7 and 5.9 and has Chrome fallback.

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
