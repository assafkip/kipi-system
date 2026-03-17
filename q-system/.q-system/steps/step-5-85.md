**Step 5.85 - Existing pipeline follow-up (daily, REQUIRED):**
> **HARNESS:** Log as `5.85_pipeline_followup`. Result = overdue count + follow-ups generated. This step CANNOT be skipped. New leads (5.9) do NOT replace following up with existing warm prospects.

This step ensures existing warm relationships don't go cold while chasing new ones. New lead sourcing (5.9) runs AFTER this, not instead of it.

**1. Pull overdue actions from Notion Actions DB:**
- Query Actions DB for Priority = Today or This Week with Due date <= today
- Also pull any actions with no Due date but Priority = Today
- Sort by age (oldest first)

**2. Pull warm DP prospects needing follow-up:**
- Query Contacts DB for Type = Design Partner AND Status = Warm or Active
- Filter for Last Contact > 7 days ago
- These people are going cold. They need a touch.

**3. Pull warm investor follow-ups:**
- Query Investor Pipeline DB for Stage != Passed AND Next Date <= today
- These have scheduled follow-up dates that are due

**4. For each overdue item, generate ONE of:**
- A copy-paste follow-up email/DM (if ball is in your court)
- A "check status" note (if ball is in their court and it's been 7+ days)
- A "close/park" recommendation (if 14+ days, 3+ touches, no response)

**5. Output: Add to HTML as "Pipeline Follow-ups" section (accent: purple)**
- This section appears BEFORE new leads in the HTML
- Each item has: person name, what's overdue, copy-paste follow-up, time estimate
- Items sorted by relationship value (active DPs first, then warm DPs, then investors, then general)

**Loop auto-close (action_created):** When querying Notion Actions DB for overdue items, also check for any actions that have been completed (moved to Someday by the stale action cleanup in Step 1, or manually marked done by founder). Cross-reference against open loops of type `action_created`:
```bash
bash q-system/.q-system/loop-tracker.sh close <loop_id> "action completed in Notion" "auto_notion"
```

**Loop opening (REQUIRED for every follow-up generated):**
Every follow-up email or DM generated in 5.85 MUST open a loop (or update touch_count on existing loop):
```bash
# For email follow-ups:
bash q-system/.q-system/loop-tracker.sh open email_sent "Person Name" "Follow-up context" "" "E1" "Next follow-up text..."
# For DM follow-ups:
bash q-system/.q-system/loop-tracker.sh open dm_sent "Person Name" "Follow-up context" "" "DM1" "Next follow-up text..."
```
If the person already has an open loop, `loop-tracker.sh open` will auto-increment touch_count instead of creating a duplicate.

**Rules:**
- MINIMUM 3 follow-up items per day in the HTML, even if nothing is technically "overdue"
- If nothing is overdue, surface the 3 warmest relationships that haven't been touched in 5+ days
- New lead sourcing (5.9) is exciting but follow-ups close deals. Follow-ups come first.
- Every follow-up gets an action card in the morning log

---
