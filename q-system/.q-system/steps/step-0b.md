- **0b - Action card pickup + missed debrief detection:**
  **HARNESS: Check for exported actions JSON FIRST (before asking the founder anything).**
  1. Check `~/Downloads/actions-YYYY-MM-DD.json` (yesterday's date)
  2. Also check `{{STATE_DIR}}/output/actions-YYYY-MM-DD.json` (backup location)
  3. If found, parse it:
     - `"done"` items = founder confirmed they did it. Update state files (LinkedIn Tracker, Contacts DB, engagement log, lead signals). No need to ask.
     - `"skipped"` items = founder chose not to. No follow-up needed. Don't surface these again.
     - Cards MISSING from the export (present in morning log but not in actions JSON) = founder never opened the HTML or didn't click the button. Only ask about THESE cards.
  4. If no export file exists at all, fall back to the previous behavior: find the most recent morning log (glob `output/morning-log-*.json`, sort by date, take the latest that is NOT today). Read its `action_cards` for any with `founder_confirmed: false`. List them and ask: "Last session I drafted these for you. Which ones did you actually do?"
  For each confirmed (from JSON or verbal): update the card, then update Notion (LinkedIn Tracker, Contacts DB, etc.). List which state files were updated in `logged_to`.
  For each not done: carry forward by adding to TODAY's action cards via the `log_add_card` MCP tool.
  **Generate effort string for today's HTML:** From the actions data (JSON export or verbal), build a summary like "8 done, 3 skipped. 5 comments posted, 2 DMs sent, 1 debrief done." Store this in the morning log so Step 11 can read it and set the `effort` field in today's schedule JSON. If no actions data exists (first run or missed day), set effort to null.
  Also check `verification_queue` for unverified claims - re-verify any that are now stale (>48h).
  **Then:** Cross-reference recent calendar events against Notion Interactions DB. Any meeting with an external person that has no matching Interaction = missed debrief. Prompt founder and run `/q-debrief`.
  **Then:** Check recent debriefs in `my-project/progress.md` for practitioner/CISO conversations that have no corresponding follow-up Action in Notion Actions DB. If a debrief happened but no design partner conversion message was sent (no Action with Type = Follow-up Email and the person's name), flag it: "[Person] conversation was debriefed but no conversion message was sent. Want me to generate one now?"
  ```
  Use the `log_step` MCP tool with date=DATE, step_id="0b_missed_debrief", status="done", result="X cards confirmed, Y carried forward, Z debriefs found"
  ```
- **0b.5 - Loop escalation and auto-close:**
  Run the loop tracker to escalate all open loops and auto-close any that have evidence of completion.
  ```
  # Escalate all loops based on age
  Use the `loop_escalate` MCP tool
  # Check stats
  Use the `kipi://loops/stats` MCP resource
  # List any loops at level 2+ (need attention)
  Use the `kipi://loops/open` MCP resource (filter for min_level=2)
  ```
  **Auto-close logic (run during Steps 1 and 3.8):**
  - Step 1 (Gmail): When scanning emails, cross-reference senders against open loops of type `email_sent` or `materials_sent`. If reply found: use the `loop_close` MCP tool with the loop_id, resolution="email reply detected", closed_by="auto_gmail"
  - Step 3.8 (DM check): When detecting DM replies, cross-reference against open `dm_sent` and `dp_offer_sent` loops. When detecting connection accepts, cross-reference against `connection_request_sent` loops. Close matches: use the `loop_close` MCP tool with the loop_id, resolution="DM reply detected", closed_by="auto_step_3.8"
  **Loop opening (run during Steps 5.85, 5.9b, 9, and /q-debrief):**
  Every outbound action that expects a response MUST open a loop:
  ```
  Use the `loop_open` MCP tool with type, target, context, and optional notion_id, card_id, follow_up_text parameters
  ```
  Types: dm_sent, email_sent, materials_sent, comment_posted, action_created, debrief_next_step, dp_offer_sent, connection_request_sent, lead_sourced
  ```
  Use the `log_step` MCP tool with date=DATE, step_id="0b.5_loop_escalation", status="done", result="X open loops (L0:X L1:X L2:X L3:X)"
  ```
