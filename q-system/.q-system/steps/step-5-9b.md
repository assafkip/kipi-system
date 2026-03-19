**Step 5.9b - Daily Engagement Hitlist (daily, COPY-PASTE READY, AUDHD rules enforced):**

> **HARNESS: Action cards.** For every engagement item generated:
> ```bash
> bash q-system/.q-system/log-step.sh DATE add-card C1 linkedin_comment "Person Name" "Comment text..." "https://linkedin.com/post-url"
> bash q-system/.q-system/log-step.sh DATE add-card C2 x_reply "Person Name" "Reply text..." "https://x.com/post-url"
> bash q-system/.q-system/log-step.sh DATE add-card C3 connection_request "Person Name" "Request note..." "https://linkedin.com/in/person"
> bash q-system/.q-system/log-step.sh DATE add-card C4 reddit_comment "u/username" "Comment text..." "https://reddit.com/thread-url"
> ```
> Types: `linkedin_comment`, `x_reply`, `connection_request`, `reddit_comment`, `linkedin_dm`, `email`
> **URL field is required** - the founder needs the link to navigate to the post.
> NEVER log to LinkedIn Tracker, Contacts DB, or any state file until `founder_confirmed: true` (next session's Step 0b).
> ```bash
> bash q-system/.q-system/log-step.sh DATE 5.9b_engagement_hitlist done "X items across Y types, X action cards"
> ```

This step generates the founder's daily engagement actions with zero searching required. Everything is copy-paste ready. Per AUDHD executive function skill: every hitlist item includes (1) the actual copy-paste text inline, (2) a direct link to the post/tweet/thread, (3) time estimate, (4) energy tag. NEVER output a hitlist item that says "copy-paste from section above." The text must be RIGHT THERE.

- **Pull engagement targets from Notion Contacts DB:**
  - Query all contacts where Type = Design Partner, VC, CISO, Connector, Advisor, Practitioner
  - Filter to those with a LinkedIn URL populated
  - Cross-reference Notion LinkedIn Tracker DB: exclude anyone engaged in the last 7 days (1 comment/person/week rule)
  - Prioritize: (1) Hot prospects from Step 5.8, (2) Design Partner prospects not yet connected, (3) Connectors/influencers, (4) VCs with upcoming meetings, (5) Everyone else

- **Scrape recent posts via Apify** (use `harvestapi~linkedin-profile-posts`):
  - **CONTEXT-SAVING: Cap at 10 targets** (not 15). Pick the 10 highest-priority from the filtered list.
  - Pull last 48h posts for top 10 engagement targets (parallel batches of 5)
  - Extract: post text, post URL, engagement count, topic
  - Skip reposts/shares (only original content worth commenting on)

- **Generate copy-paste comments** for each post found:
  - Style by pool: VCs get domain insight, practitioners get peer validation, connectors get amplification
  - 2-3 sentences max, no {{YOUR_PRODUCT}} pitch
  - Reference something specific from their post (not generic "great insights")
  - Must pass test: "Does this comment add value to the conversation?"
  - **VOICE RULE: Stay on the person's topic. Do NOT steer every comment toward your product's domain.** The founder's credibility is their professional experience, not their product category. If someone posts about ownership gaps, comment about ownership gaps. If someone posts about governance, comment about governance. If someone posts about silos, comment about silos. Only mention your domain if THEY mentioned it. The goal is to be a thoughtful practitioner voice on THEIR topic, not to position yourself as a domain expert.

- **Also pull X/Twitter activity** for contacts with X handles:
  - Use Apify Twitter scraper for last 48h tweets from key handles
  - Generate copy-paste replies (1-2 sentences, sharper than LinkedIn)
  - Same voice rule: reply to what THEY said. Don't pivot to your domain.

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
  - [ ] LinkedIn comments: Apify post scrape ran for top 15 targets. If 0 posts found, state "0 posts found in last 48h for [N] targets scraped" - do NOT silently skip.
  - [ ] X/Twitter replies: Apify tweet scrape ran for contacts with X handles. If 0 tweets found or no contacts have X handles, state the reason.
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
