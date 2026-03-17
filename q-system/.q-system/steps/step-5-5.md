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
