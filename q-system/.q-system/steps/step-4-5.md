- **Marketing actions from Step 4.5:** If stale assets found, create Action "Refresh stale marketing assets" (Energy: Deep Focus, Time: 30 min, Type: Other). If Gamma decks need review, create Action "Review Gamma deck for positioning changes" (Energy: Deep Focus, Time: 15 min). If content is behind cadence, create Action for missing content (Energy: Deep Focus, Time: 15-30 min). If drafts ready for review, create Action "Review [draft name]" (Energy: Quick Win, Time: 5 min).
- **Loop opening for non-trivial actions:** Every Notion Action created that expects a response or has a deadline MUST open a loop:
  ```bash
  bash q-system/.q-system/loop-tracker.sh open action_created "Action title" "Context" "" "ACT-XXX"
  ```
  Skip loop opening for: meeting prep (completed same day), admin tasks, internal-only items. Open loops for: follow-up emails, debrief next steps, intro requests, research with a deadline.
