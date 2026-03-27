# Q Instance Commands

> These are conventions for interacting with the Q Founder OS. Use them as natural language triggers — they tell Claude which mode to enter and what to do.

| Command | Purpose | Mode |
|---------|---------|------|
| `/q-begin` | Start a new session. Claude reads all canonical files first to load current state. | — |
| `/q-status` | Report current state from `my-project/progress.md`. Quick snapshot of where things stand. | — |
| `/q-calibrate` | Enter Calibrate mode. Update canonical files based on new information, feedback, or market changes. | CALIBRATE |
| `/q-create [type] [audience]` | Enter Create mode. Generate a specific output (talk track, email, slide text, diagram, memo) for a specific audience. | CREATE |
| `/q-debrief [person]` | Enter Debrief mode. Use the structured debrief template to process a conversation. Includes 12 strategic implications lenses, market intelligence routing, and **Design Partner Conversion** (mandatory for practitioner/CISO calls - produces copy-paste message to convert conversation into trial). **Highest-priority workflow.** | DEBRIEF |
| `/q-plan` | Enter Plan mode. Review relationships, objections, and proof gaps. Propose prioritized next actions. | PLAN |
| `/q-draft [type] [audience]` | Generate an ad-hoc output to `output/drafts/`. For one-off emails, DMs, talking points. Ephemeral. | CREATE |
| `/q-ingest-feedback [file]` | Process a feedback file from `seed-materials/`. Extract objections, resonance phrases, competitive intel, market intelligence, and contact context into canonical files. Also evaluates for market intelligence (problem language, category signals, objection previews, competitive intel, buyer process, narrative validation) and routes to `canonical/market-intelligence.md`. | CALIBRATE |
| `/q-checkpoint` | Save current canonical state. Verify all files are consistent. Log to `my-project/progress.md`. Update `memory/morning-state.md` checkpoint timestamp. | — |
| `/q-end` | End session. Auto-runs `/q-checkpoint` first, then summarizes all changes. | — |
| `/q-sync-notion` | Sync local files ↔ Notion CRM. Push new contacts/interactions/pipeline changes to Notion. Pull follow-up date changes and status updates from Notion back to local files. | CALIBRATE |
| `/q-morning` | Morning briefing. Runs calendar + email + Notion checks in parallel, surfaces unlogged interactions, checks decision rule compliance, flags stale positioning. See workflow below. | — |
| `/q-engage` | LinkedIn engagement mode. Proactive: generate daily hitlist from Notion targets. Reactive: user shares post screenshot → comment suggestions + auto-log to Notion. See workflow below. | CREATE |
| `/q-content-intel` | Content intelligence. Scrape own content across all platforms via Apify. Analyze what works vs. doesn't. Update `canonical/content-intelligence.md`. Cross-reference themes against `canonical/market-intelligence.md` to check if our content topics align with what the market is discussing. Score drafts before publishing. | CALIBRATE |
| `/q-investor-update` | Draft a milestone-triggered investor update email for the full VC list. Pulls pipeline, recent wins, metrics. Batch send-ready. | CREATE |
| `/q-market-plan` | Weekly content planning. Reads theme rotation + editorial calendar. Generates this week's plan. Creates Notion entries in Content Pipeline + Editorial Calendar DBs. | CREATE |
| `/q-market-create [type] [topic]` | Generate marketing content. Types: linkedin, x, medium, one-pager, outreach, deck, follow-up. Reads canonical files + templates + NotebookLM. Runs guardrails. For deck/one-pager, generates via Gamma MCP. See workflow below. | CREATE |
| `/q-market-review [file]` | Validate content against `marketing/content-guardrails.md`. PASS/FAIL with specific fixes. | — |
| `/q-market-publish [file]` | Mark content published. Update Content Pipeline DB status. Log to `memory/marketing-state.md` publish log. | — |
| `/q-market-assets` | Refresh all reusable assets in `marketing/assets/` from canonical files. Flag stale items. Flag Gamma decks needing re-generation. Update Asset Library DB. | CALIBRATE |
| `/q-market-status` | Quick snapshot: Content Pipeline counts, cadence progress, asset health, Gamma deck status. | — |
| `/q-wrap` | Evening wrap. 10-min end-of-day system health check. Closes open loops, catches missed debriefs, previews tomorrow. | — |
| `/q-handoff` | Session handoff. Generates context note for next session. Run before ending or when context is running low. | — |
| `/q-reality-check` | Challenger mode. Stress-tests current positioning, claims, and assumptions against evidence. | — |

## Usage Notes

- **`/q-morning` is the only command you need to start a day.** It auto-checkpoints the previous session, catches missed debriefs, and loads canonical state. No need to run `/q-begin` or `/q-end` separately.
- **Debriefs happen automatically.** Paste a conversation transcript and Claude auto-runs `/q-debrief`. No command needed. If you forget, `/q-morning` catches missed debriefs the next day.
- `/q-begin`, `/q-end`, and `/q-checkpoint` still work if you want to use them manually, but they're no longer required.
- **`/q-draft` vs `/q-create`:** Use `/q-create` for structured deliverables (talk tracks, workflow packs). Use `/q-draft` for one-off outputs (specific email, DM, talking points for a meeting).
- **`/q-ingest-feedback [file]`** expects a file in `seed-materials/`. Place the file there first.
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
2. For each target: Use Apify LinkedIn Posts Scraper actor to pull their last 7 days of posts. Run in parallel batches of 5. Fall back to Chrome only if Apify fails.
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
1. **Research** (parallel via Apify): Use LinkedIn Profile Scraper + LinkedIn Posts Scraper actors to pull each prospect's profile data AND recent posts/activity in parallel. This replaces Chrome browser automation and runs faster at lower cost. Extract:
   - What they post/comment about (topics, themes, pain points)
   - Specific recent posts (quotes, subjects)
   - Professional focus areas and what they care about
   - Any angles connecting to {{YOUR_PRODUCT}}'s positioning
2. **Personalize** using the `cold-email` marketing skill: For each prospect, craft:
   - Touch 1 comment (if they have recent posts to comment on)
   - Connection request (under 300 chars) referencing something specific from their activity
   - Follow-up DM (under 500 chars) referencing their specific work, asking a genuine question, with UTM-tagged demo link as async CTA (e.g., `{{YOUR_DEMO_URL}}?utm_source=linkedin&utm_medium=dm&utm_campaign=cold-outreach&utm_content=[prospect-slug]`)
3. **Save** all messages to `output/design-partner/personalized-outreach-YYYY-MM-DD.md`
4. **Update Notion** contacts with research findings (What They Care About, Follow-up Action, Strategic Value)
5. **Output** execution sequence (who to contact first, Touch 1 vs Touch 2)

**Rules for DP outreach personalization (MANDATORY):**
- Every message MUST reference something specific the person wrote, shared, spoke about, or cares about
- Generic templates with only name/company swapped are NOT acceptable
- Use Apify LinkedIn Profile + Posts Scraper actors for research (parallel, cheaper than Chrome). Fall back to Chrome only if Apify fails.
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
