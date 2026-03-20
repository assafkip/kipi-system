LinkedIn engagement mode. Read the full workflow from q-system/.q-system/commands.md under "LinkedIn engagement".

Arguments: $ARGUMENTS

Two sub-modes:

**If argument is "dp-outreach":** Run design partner outreach personalization.
1. Research prospects via Chrome (parallel agents per prospect)
2. Personalize using cold-email marketing skill
3. Save to output/design-partner/personalized-outreach-YYYY-MM-DD.md
4. Update Notion contacts with research
5. Output execution sequence

**If no argument (proactive mode):**
1. Pull Contacts DB for Type = VC, Design Partner, CISO, Advisor with Status = Active or Warm
2. Open LinkedIn profiles in Chrome for recent activity
3. Cross-reference with Notion history
4. Output daily engagement hitlist

**If user shares a LinkedIn post screenshot (reactive mode, no command needed):**
1. Identify person + pool
2. Check Notion Contacts DB
3. Generate 2-3 comments (Insight / Connector / Question styles)
4. After founder picks: log to Notion (Contact + LinkedIn Tracker entry)

Rules: Never pitch the product in comments. Max 3-4 sentences. One comment per person per week. Always log to Notion.
