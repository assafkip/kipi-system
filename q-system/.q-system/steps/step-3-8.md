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
  bash q-system/.q-system/loop-tracker.sh close <debrief_loop_id> "next step completed - email sent" "auto_step_3.8"
  # The email_sent loop was already opened by Step 9 or 5.85
  ```
  Also: during Step 0b action card confirmation, if the founder confirms a card that matches a debrief_next_step loop's action_card_id, auto-close:
  ```bash
  bash q-system/.q-system/loop-tracker.sh close <loop_id> "action card confirmed by founder" "founder"
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
  bash q-system/.q-system/loop-tracker.sh close <loop_id> "DM reply detected" "auto_step_3.8"
  # For each connection accept detected:
  bash q-system/.q-system/loop-tracker.sh close <loop_id> "connection accepted" "auto_step_3.8"
  # For dp_offer_sent loops where target replied via DM:
  bash q-system/.q-system/loop-tracker.sh close <loop_id> "DP replied to offer" "auto_step_3.8"
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
- Notion: `mcp__notion__notion-search`, `mcp__notion__notion-fetch`, `mcp__notion__notion-update-page`, `mcp__notion__notion-create-pages`
- Apify (primary for data scraping): `mcp__apify__*` - LinkedIn Profile/Posts Scraper, Twitter/X Scraper, Web Scraper (Medium, Reddit, Substack). Use for all structured data collection. Cheaper and faster than Chrome.
- Chrome (interactive + DMs): `mcp__claude-in-chrome__*` - Use for: LinkedIn DM reading (Step 3.8), posting comments/replies, checking notifications, LinkedIn Comments tab, Google Analytics, visual content review. NOT for profile/post scraping (use Apify).
- VC Pipeline Manager: `http://localhost:5050/api/pipeline` (GET) - Returns full VC pipeline with 66+ contacts, warm intro paths, tiers, statuses. Use `WebFetch` to pull. Data source for warm intro matching (Step 1.5) and cross-referencing connectors. App at `http://localhost:5050/`.
- NotebookLM: `mcp__notebooklm__add_notebook`, `mcp__notebooklm__ask_question`, `mcp__notebooklm__search_notebooks`
- Signals: `WebFetch` on `https://{{YOUR_DOMAIN}}/signals`
- Google Analytics (Mondays): `mcp__claude-in-chrome__*` on `analytics.google.com` (authuser=2, property a385692819p526076376)
- Gamma: `mcp__gamma__generate_gamma`, `mcp__gamma__get_gamma_generation`

---

### Content intelligence (`/q-content-intel`):

> Scrape your own content across all platforms. Analyze what works vs. what doesn't. Build a data-driven content scoring model.

**Full run (weekly, or on demand):**

1. **Scrape all platforms via Apify** (`mcp__apify__*`):
   - **LinkedIn:** LinkedIn Posts Scraper actor on founder's profile. Pull last 30 days of posts. Extract: text, impressions, likes, comments, reposts, date/time posted.
   - **X/Twitter:** Twitter/X Scraper actor on @{{YOUR_X_HANDLE}}. Pull last 30 days. Extract: text, impressions, likes, retweets, replies, quotes, date/time.
   - **Medium:** Web Scraper actor on {{YOUR_MEDIUM_PROFILE}}. Pull all articles. Extract: title, reads, claps, read ratio, responses, publish date.
   - **Reddit:** Reddit Scraper actor on founder's posts. Pull last 30 days. Extract: title, subreddit, upvotes, comments, upvote ratio.
   - **Substack:** Web Scraper actor on {{YOUR_SUBSTACK_PROFILE}}. Pull newsletter stats. Extract: title, open rate, click rate, subscriber count.

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

**Apify cost estimate:** ~$2-4 per full run (LinkedIn profiles + posts + X tweets + web scraping). Well within free tier for weekly cadence.

---

### Investor update (`/q-investor-update`):

> Milestone-triggered investor update email. Drafts a concise, high-signal update for the full VC list. Not a newsletter - a founder update that makes VCs feel like insiders.

**When to run:** When `/q-morning` Step 9.5 flags an update is due, or on demand after a milestone.

**Workflow:**

1. **Pull current state:**
   - Read Investor Pipeline DB (see `my-project/notion-ids.md` for DB ID) for all VCs with status != Passed
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
     {{FOUNDER_FIRST_NAME}}
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

Workflow for each type:
1. Read the corresponding template from `marketing/templates/`
2. **Read `canonical/content-intelligence.md`** for current performance patterns. Use high-performing language, formats, and hooks. Avoid low-performing patterns. This step is MANDATORY for linkedin, x, and medium types.
2.1. **Read `canonical/market-intelligence.md`** for buyer language and market signals. When writing about a topic, use the verbatim problem language from practitioners instead of our marketing copy where possible. If the market-intelligence file has relevant category signals or objection previews, address them in the content. This step is MANDATORY for linkedin, x, medium, and outreach types.
2.5. **Read `marketing/brand-kit.html`** for visual identity (colors, fonts, components, layout patterns). This step is MANDATORY for one-pager, deck, and any HTML/visual output. For linkedin, x, and medium types, reference the brand kit when generating any accompanying visual assets (social cards, carousels, banners). Use the CSS variables (--k- prefix), type scale, component patterns, and CNS color naming from the kit.
3. Follow template's pre-generation steps (canonical sources, NotebookLM queries, CRM lookup)
4. Generate content following template structure, informed by content intelligence patterns
5. **Generate Gamma visual (MANDATORY for all content types except outreach/follow-up):**
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
- Parent page: (see `my-project/notion-ids.md`)

**NotebookLM:**
- Marketing Knowledge Base notebook: (see `my-project/notion-ids.md` or configure during setup)

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

Read `.claude/skills/evening-wrap/SKILL.md` for the full workflow (5 steps).

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

Read `.claude/skills/session-handoff/SKILL.md` for the full spec.

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