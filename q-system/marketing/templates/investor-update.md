# Template: Investor Update Email

> Used by `/q-investor-update`
> Milestone-triggered, not calendar-triggered. Send when there's something worth sharing.

---

## Pre-Generation Steps

1. **Pull metrics** from progress.md and current-state.md
2. **Check decisions.md** for major decisions since last update
3. **Check relationships.md** for investor context (what they care about, last touchpoint)
4. **Pull pipeline state** from CRM or relationships.md
5. **Check canonical files** for any positioning changes to highlight

## Structure

```
Subject: [Company] Update - [Month] | [One-line highlight]

[Investor name] -

**Highlights**
- [Win 1 - the biggest, most concrete]
- [Win 2 - traction, validation, or milestone]
- [Win 3 - team, product, or market signal]

**Metrics**
| Metric | Last Update | Now | Delta |
|--------|------------|-----|-------|
| [Key metric 1] | | | |
| [Key metric 2] | | | |
| [Key metric 3] | | | |

**What's working:**
[1-2 sentences on what's gained traction and why]

**What's not:**
[1-2 sentences on what's stalled or pivoted. Be honest.]

**Ask:**
[One specific, actionable ask. Intro, feedback, signal boost, hiring lead.]

**Next milestones:**
- [Milestone 1 - with target date]
- [Milestone 2 - with target date]

{{YOUR_NAME}}
```

## Rules

- Under 500 words total
- Lead with wins, be honest about misses
- One clear ask, not three
- Metrics table is required (even if small)
- "What's not working" section is required (builds trust)
- No "exciting" / "thrilled" / "incredible traction"
- Send from personal email, not a newsletter tool
- BCC if sending to multiple investors (or personalize per-investor)

## Output Format

Save to: `output/marketing/investor-updates/investor-update-YYYY-MM-DD.md`

## Post-Generation

1. Run voice skill on the draft
2. Personalize per-investor if asks differ
3. Log send date in relationships.md
