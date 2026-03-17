**Step 3.2 - Post-publish reconciliation (LinkedIn):**

Detects content published directly (not through Q) and updates tracking to match reality.

- **Compare Apify LinkedIn data (from Step 3) against Content Pipeline DB:**
  - Pull all posts from the Apify LinkedIn scrape (Step 3 already has this data)
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
- **Also check X/Twitter** (from Step 2.5 Apify data): Same reconciliation for tweets. Match against Content Pipeline DB entries with Type = X Post.
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
