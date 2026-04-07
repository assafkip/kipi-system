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

> **The morning routine is now fully handled by the agent pipeline.**
> Read `.q-system/agent-pipeline/agents/step-orchestrator.md` for the phase plan.
> Read `.q-system/preflight.md` before every run.
> Individual agent prompts are in `.q-system/agent-pipeline/agents/`.
> Bus files land in `.q-system/agent-pipeline/bus/{date}/`.

(Legacy step-by-step instructions removed. The agent pipeline is the source of truth.)


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
- Edit queue: saved to `output/` on first use

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
