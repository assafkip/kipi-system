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
