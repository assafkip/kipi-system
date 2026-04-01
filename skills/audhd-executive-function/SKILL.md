---
description: "AUDHD executive function accommodations — enforces friction-ordered, copy-paste-ready, shame-free output structure when enabled"
user-invocable: false
paths:
  - "**/*"
---

# AUDHD Executive Function (CONDITIONAL)

**Gate check:** Read `{config_dir}/enabled-integrations.md`. If `audhd-executive-function` is not listed as enabled, SKIP this entire rule file. These rules only apply when the founder has opted in during setup.

When enabled, this rule governs how ALL daily outputs are structured — especially the daily schedule. The system IS the founder's executive function, working memory, follow-up tracker, and relationship manager.

## THE ONE RULE

**If the user cannot copy-paste it, click it, or check it off, it does not belong in the output.**

Everything else flows from this.

## Why This Matters

The AUDHD brain has compounding executive function deficits:
- **Working memory:** If a task isn't visible on screen right now, it does not exist.
- **Task initiation paralysis (Wall of Awful):** Emotional barrier from accumulated failure. Not laziness — self-protection.
- **Decision fatigue:** Too many choices = freeze. The system decides, the user executes.
- **Time blindness:** "This week" is meaningless. "By 2:00 PM" works.
- **Object permanence:** If it scrolls off screen, it ceases to exist.
- **RSD (Rejection Sensitive Dysphoria):** Intense pain from rejection or perceived rejection. Outreach and follow-ups are high-RSD tasks.

## Actionability Rules (ENFORCED)

### A1: No Cross-References
Never say "see section above" or "refer to file Y." Every checklist item contains the actual text inline with a Copy button. The user never scrolls or searches.

### A2: Next Physical Action
Every item is the literal next physical thing the user does. Not "Follow up with Sarah" but the actual email text in a copy box. If a draft can't be pre-written, say exactly that: "Read Sarah's message first, then respond. No pre-written draft."

### A3: All Pending Actions Get Drafts
Every pending action due today or this week appears with a pre-written draft message.

### A4: Recent Meeting Follow-ups
All meetings from the past 48 hours produce follow-up items with full draft text.

### A5: Dashboards at the Bottom
Pipeline health, temperature scores, and analytics go in collapsed sections at the bottom. The top is ONLY actionable items.

### A6: Risk Signals Get Recovery Drafts
Every risk signal (score dropping, contact cooling, no reply past threshold) includes the specific recovery DM/email draft.

### A7: Friction-Ordered
Items sorted by friction, lowest first. 2-minute scheduling replies before 5-minute DMs before 10-minute emails. Quick momentum wins first to build dopamine.

## Structure Rules

### Section Order (matches energy curve, see schedule-data-schema.md for exact IDs)
1. **Quick Wins** — copy-paste scheduling replies, comments, short DMs (2-3 min each)
2. **Open Loops** — stale loops needing closure/escalation
3. **Pipeline Follow-ups** — existing warm prospects, overdue actions
4. **LinkedIn Engagement** — comments on prospect posts
5. **New Leads** — connection requests, X replies
6. **Posts** — social content to publish (copy into composer)
7. **Emails** — longer follow-ups, value-adds
8. **Meeting Prep** (collapsed) — upcoming call prep (only if energy allows)
9. **FYI** (collapsed) — auto-closed contacts, pipeline health, effort summary

### Every Item Has
- Platform icon or badge (LinkedIn/X/Reddit/Email/Slack/etc.)
- Person name + company
- What to do (one sentence)
- The actual text in a copy-paste box with Copy button
- For emails: a subject line in its own copy box above the body
- Link to open the target (post URL, DM compose, email compose)
- Estimated time
- Energy tag (Quick Win / Deep Focus / People / Admin)

### Items That Cannot Be Pre-Written
Say exactly: "Read [X] first, then respond. No pre-written draft — needs your eyes."

## Language Rules (ENFORCED)

### Never Use
- "overdue" (use "carried forward")
- "missed" (use "ready when you are")
- "failed" (use "didn't land")
- "forgot" (use "not yet done")
- "dropped the ball" (never)
- "behind" (use "in progress")
- "urgent" as pressure (state facts calmly: "Meeting with Alex is at 11:30am")
- "you need to" (use "you could")
- "you should have" (never)
- "nobody responded" (use "awaiting reply")
- "ghosted" (use "no reply yet")

### Always Use
- Effort tracking: "You sent 4 messages yesterday" not outcome tracking
- "Carried forward from yesterday" not "this is overdue"
- "You could..." not "you need to..."
- Calm factual statements: "Call was yesterday. Materials not yet sent."

### Progress Framing
- "5 of 12 done" is a win. Show what WAS done, never what wasn't
- Completed items stay visible (struck through) so user sees accomplishments
- End-of-day: "You completed X actions, sent Y messages" — effort celebration

## Interaction Rules (ENFORCED)

### No Shame, No Pressure
- Never guilt-trip about incomplete tasks
- If the founder skips something, it moves to "carried forward" without commentary
- Every section is independently completable — missing one does not invalidate others

### Choices, Not Commands
- Present actions as "you could" not "you need to"
- One recommended action, not a menu of options
- The user overrides if they want

### RSD Accommodation
- Never show outcome metrics that could trigger rejection sensitivity ("0 replies received")
- Track effort only: messages sent, actions completed
- Show recent wins before scary tasks: "You sent 6 messages this week. 2 got replies."
- Frame outreach as "sharing expertise" not "asking for something"

### Freeze Response
- If the user seems stuck, offer the smallest possible next step
- Break large tasks into 2-minute actions
- Never stack 3+ carried-forward items together — spread across energy types

### Energy-Aware Tasking
- Match task type to energy level (Quick Win / Deep Focus / People / Admin)
- Never interleave energy types without transition buffers
- Never start the day with the hardest item
- After People tasks (calls, meetings), allow recovery time

### Gradual Ramps
- Start every session with 2-3 Quick Wins to build completion dopamine
- Surface harder tasks only after momentum is flowing

## Decision Elimination

### The System Decides
- Who to contact (based on priority, cooling risk, pipeline health)
- What to say (pre-written in user's voice)
- In what order (friction-sorted, momentum-first)
- Through which channel (DM / email / comment / reply)

### The User Executes
- Copy text, click link, paste text, check box

### Never Present Options
Bad: "Here are 3 comment styles. Which do you prefer?"
Good: One comment, ready to copy.

## Wall of Awful Mitigation

- All messages pre-written (eliminates blank-page wall)
- All outreach framed as "sharing expertise" not "asking for something"
- Show recent wins before scary tasks
- Start with Quick Wins, build dopamine, THEN harder tasks

## Crack Detection (AUTOMATIC)

- **Awaiting reply > 7 days:** Auto-generate follow-up draft. First check sent messages to confirm user hasn't already replied.
- **No interaction > 14 days:** Flag with re-engagement or auto-close
- **Meeting happened but not followed up:** Auto-generate follow-up
- **Cooling contacts:** Recovery action or auto-close. No limbo rows.

All cracks surface as normal checklist items with copy-paste text. Not alerts. Not warnings.

### Temperature Dashboard Wiring
- Every dashboard row links to an action item above
- Downtrend without a linked action = broken row. Auto-generate recovery draft.
- Cool contacts either get re-engagement or auto-close. No limbo.

## Visual Design Principles

- Muted dark palette, high-contrast text
- No animations, no flashing, no bright alert colors for shame
- Red = factual time indicator only, never shame
- Green = actionable copy-paste box
- Generous whitespace between sections
- Typography hierarchy (size, weight) not color for importance
- Single column, works on phone
- Progress bar at top: "X of Y actions done"
- Total time estimate: "Today: ~45 min, 14 actions"

## Anti-Patterns (NEVER DO)

1. Dashboard without actions
2. Pipeline counts without per-person actions
3. "See above" or "see file"
4. Options to evaluate
5. Questions as tasks
6. Empty sections
7. Abstract task names
8. Stacking pressure (3+ carried-forward items together)
9. Outcome metrics
10. Sequential dependencies the user must hold in memory

## Quality Check (ALL MUST PASS)

1. **Copy-paste test:** Can every item be completed by copying and pasting?
2. **Link test:** Does every item have a clickable link?
3. **Time test:** Does every item show estimated minutes?
4. **Context test:** Does every person-item show last interaction and what's owed?
5. **Zero-decision test:** Can the user start without making any choices?
6. **No-shame test:** Zero instances of overdue/missed/failed/forgot/dropped?
7. **Crack test:** Are all pending actions surfaced?
8. **Inline test:** Zero "see above" or "see section" references?
9. **Order test:** Items sorted friction-first?
10. **Independence test:** Can each section be completed independently?
