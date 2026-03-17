**Step 11 — Generate daily schedule JSON + build HTML + open in browser:**

> **GATE CHECK (mandatory before starting Step 11):**
> Re-read morning log from disk. Check Steps 0f through 10 all logged (including `9_notion_push` and `10_daily_checklists`).
> `bash q-system/.q-system/log-step.sh DATE gate-check step_11 true ""`
> If missing steps: `bash q-system/.q-system/log-step.sh DATE gate-check step_11 false "missing_step_ids"` then STOP.
> **Recovery:** If the gate fails, list the missing steps and ask the founder: "These steps didn't run: [list]. Options: (1) I go back and run them now, (2) you tell me to skip them and I'll log them as skipped, (3) we end the session and restart fresh." The founder decides. Claude does NOT self-authorize skipping.

**MANDATORY PRE-CHECK: Re-read `.claude/skills/audhd-executive-function/SKILL.md` before generating.** The daily HTML is the founder's external executive function, not a briefing. Apply all rules.

**HOW IT WORKS:** Claude writes a JSON data file. A build script injects it into a locked-down HTML template. Claude NEVER writes raw HTML.

1. **Read the schema:** `marketing/templates/schedule-data-schema.md` defines the exact JSON format.
2. **Generate JSON:** Write `output/schedule-data-YYYY-MM-DD.json` conforming to the schema.
3. **Build HTML:** Run `bash marketing/templates/build-schedule.sh output/schedule-data-YYYY-MM-DD.json output/daily-schedule-YYYY-MM-DD.html`
4. **Open in browser:** `open output/daily-schedule-YYYY-MM-DD.html` or use Chrome MCP.
5. **Telegram push (if configured):** Send top 3 actions via Telegram MCP.

**JSON content checklist (combine everything from Steps 1-10):**
- `effort`: Yesterday's effort summary (actions taken, not outcomes)
- `callBanners`: Today's meetings from calendar (time, person, link)
- `sections` in this order:
  1. **Quick Wins** (`green`): scheduling replies, short DMs, comments (2-3 min each)
  2. **LinkedIn Engagement** (`blue`): comments from Step 5.9b hitlist
  3. **New Leads** (`yellow`): connection requests + X replies from Step 5.9
  4. **Special Outreach** (`pink`): event outreach, batch campaigns (only when applicable)
  5. **Posts** (`green`/`yellow`): social content drafts (collapsed if published)
  6. **Emails** (`purple`): longer follow-ups, value-adds
  7. **Meeting Prep** (`purple`, collapsed): upcoming call prep with context
  8. **FYI** (`gray`, collapsed): pipeline health, signals, info-only notes

**Engagement hitlist validation:** The hitlist sections MUST mirror Step 5.9b (LinkedIn Comments, X/Twitter Replies, Connection Requests, Reddit Comments). If any type has 0 results, include the section with an info note "None today - [reason]".

**Lead sourcing results:** Qualified prospects from Step 5.9 appear as items with names, titles, post previews, and copy-paste connection requests. Show RESULTS, not search links.

**The template is LOCKED.** All CSS, JS, rendering logic lives in `marketing/templates/daily-schedule-template.html`. Never edit it during morning routine. Never write raw HTML. If a visual bug is found, fix the template in a separate session.

**ACTIONABILITY RULES (ENFORCED - every item in HTML must pass these):**

**Rule A1:** NEVER use cross-references. Never say "Copy-paste from section above" or "See Lead Sourcing section." Every checklist item must contain the actual copy-paste text inline with a Copy button. The user should never scroll or search to find what to send.

**Rule A2:** EVERY checklist item must include the NEXT PHYSICAL ACTION. Not "Follow up with Ryan Hand" but the actual email/DM text ready to copy. Not "Reply to 14 Peaks" but "Hi Cora, Thursday March 12 at 11am ET works great." If a draft can't be pre-written (e.g., "Review Mark's advisory agreement"), say exactly that: "Read the DM first, then respond. No pre-written draft - needs your eyes."

**Rule A3:** EVERY pending Notion Action with Priority "Today" or "This Week" and a Due date <= today must appear in the HTML with a draft message. Query the Actions DB during morning routine and convert every pending action into a copy-paste item.

**Rule A4:** ALL debriefs from the past 48 hours must produce follow-up items in the HTML. If a call happened yesterday, the follow-up email/DM must be in today's Quick Wins with full draft text.

**Rule A5:** Pipeline/temperature dashboards are INFORMATIONAL ONLY. They go in a collapsed section at the bottom. The top of the HTML is ONLY actionable items with copy-paste text. Never put a dashboard item without an attached action and draft.

**Rule A6:** For any risk signal (score dropping, contact cooling), the HTML must include the specific recovery action with draft text. "Phil Venables score 5, dropping" becomes a DM draft. "Costanoa no reply 8 days" becomes a nudge email draft.

**Rule A7:** Items are ordered by friction, lowest first. 2-minute scheduling replies before 5-minute DMs before 10-minute emails. Quick momentum wins first to build dopamine.
