# PRD Template

Use this template for all product/system changes. Fill every section. If a section doesn't apply, write "N/A" with a one-line reason.

---

```markdown
# PRD: [Title]

**Date:** YYYY-MM-DD
**Author:** [Name]
**Status:** Draft | In Review | Approved | Implementing | Done
**Priority:** P0 (blocking) | P1 (high) | P2 (medium) | P3 (low)

---

## 1. Problem

What's broken, missing, or slow. Ground in data, not opinion.

- **Evidence:** Link to report, metrics, incident, or user feedback
- **Impact:** Who is affected, how often, and what it costs (time, errors, friction events)
- **Root cause:** Why the problem exists (not just what it looks like)

## 2. Scope

### In Scope
Bulleted list of what this PRD covers.

### Out of Scope
Bulleted list of related work this PRD explicitly does NOT cover. Include why (deferred, separate PRD, not worth the cost).

### Non-Goals
Things this change is NOT trying to achieve, even if they seem related.

## 3. Changes

For each change:

### Change N: [Name]

- **What:** One-sentence description
- **Where:** Exact file path(s)
- **Why:** Which problem/evidence this addresses (trace back to Section 1)
- **Exact change:** Code block or diff showing the precise addition/modification
- **Scope:** Who/what inherits this change (global, skeleton, single instance)

## 4. Change Interaction Matrix

How do the changes behave when they overlap? Fill one row per pair that could interact.

| Change A | Change B | Interaction | Resolution |
|----------|----------|-------------|------------|
| ... | ... | What happens when both fire | Which takes precedence, or how they compose |

## 5. Files Modified

| File | Change Type | Lines Added | Lines Removed |
|------|------------|-------------|---------------|
| ... | Add / Edit / Delete | +N | -N |

## 6. Test Cases

Tag each test as:
- **DET** (deterministic) = can be verified by running a command and checking output
- **BEH** (behavioral) = verified by observing LLM behavior over multiple sessions
- **INT** (integration) = requires end-to-end system run

### [Change N] Tests

| # | Type | Scenario | Input | Expected | Pass Criteria |
|---|------|----------|-------|----------|---------------|
| N.1 | DET/BEH/INT | ... | ... | ... | ... |

Include at least 1 negative test per change (scenarios where the rule should NOT fire).

## 7. Regression Tests

Existing behavior that must not break.

| # | What to Verify | How to Verify | Pass Criteria |
|---|----------------|---------------|---------------|
| R-1 | ... | ... | ... |

## 8. Rollback Plan

| Change | Rollback Steps | Risk |
|--------|---------------|------|
| ... | Exact steps to undo | What could go wrong during rollback |

## 9. Change Review Checklist

Run before approving.

| Check | Status | Notes |
|-------|--------|-------|
| Changes are additive (no breaking removals) | | |
| No conflicts with existing enforced rules | | |
| No hardcoded secrets | | |
| Propagation path verified (kipi update, global, etc.) | | |
| Exit codes preserved (hooks exit 0) | | |
| AUDHD-friendly (no pressure/shame language added) | | |
| Test coverage for every change | | |

## 10. Success Metrics

| Metric | Current | Target | How to Measure |
|--------|---------|--------|----------------|
| ... | ... | ... | Exact command, report, or process to get this number |

## 11. Implementation Order

Numbered list with dependencies noted. Each step should be independently deployable if possible.

## 12. Open Questions

Unresolved decisions. Each must have an owner and a deadline.

| Question | Owner | Deadline | Resolution |
|----------|-------|----------|------------|
| ... | ... | ... | Filled in when decided |

## 13. Wiring Checklist (MANDATORY)

A PRD is not done when the changes are implemented. Done = every artifact is discoverable and enforced. Complete every row before marking Status as "Done."

| Check | Status | Notes |
|-------|--------|-------|
| PRD file saved to `q-system/output/prd-<slug>-YYYY-MM-DD.md` | | |
| All code/config changes implemented and tested | | |
| New files listed in folder-structure rule (if any created) | | |
| New conventions referenced in root CLAUDE.md (if any added) | | |
| New rules referenced in folder-structure rules list (if any created) | | |
| Memory entry saved for decisions/patterns worth recalling | | |
| `kipi update --dry` confirms propagation diff (if skeleton files changed) | | |
| `kipi update` run to push to all instances (if skeleton files changed) | | |
| PRD Status field updated to "Done" | | |
```

---

## Template Usage Rules

- One PRD per logical change set. Don't combine unrelated work.
- Every change must trace back to evidence in Section 1. No "while we're at it" additions.
- Out of Scope is mandatory. If you can't name what you're NOT doing, the scope is undefined.
- Behavioral tests (BEH) must state the observation window ("verified over next 2 weeks via insights report").
- The Change Interaction Matrix catches rule conflicts before they ship. Skip it only for single-change PRDs.
- PRDs live in `q-system/output/prd-*.md`. Templates live here.
- The Wiring Checklist (Section 13) is mandatory. A PRD with unfinished wiring is not done.
