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
  | Posted about KTLYST-shaped problem | +3 | Step 5.9 (problem-language search) |
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
