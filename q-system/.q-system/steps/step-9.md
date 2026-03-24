**Step 9 — Offer fixes + push actions to Notion:**

> **GATE CHECK (mandatory before starting Step 9):**
> Re-read morning log from disk (same check as Step 8, plus `8_briefing_output` and `8.5_start_here`).
> `bash q-system/.q-system/log-step.sh DATE gate-check step_9 true ""`
> If missing steps: `bash q-system/.q-system/log-step.sh DATE gate-check step_9 false "missing_step_ids"` then STOP.

- If violations or pending propagation found, offer to fix immediately
- If unlogged emails found, offer to create Notion interactions
- If LinkedIn follow-ups overdue, offer to generate comment suggestions
- **ALWAYS create Notion Actions** for every actionable item surfaced in the briefing (meeting prep, follow-ups due, emails to send, debriefs to run, LinkedIn re-engagements). Use Actions DB (DB 0718ee69-d9d0-473d-8182-732d21c60491). Set Energy, Time Est, Priority, Type, Due date, and Contact link for each.