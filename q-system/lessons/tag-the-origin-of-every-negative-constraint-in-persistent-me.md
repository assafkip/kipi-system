---
id: tag-the-origin-of-every-negative-constraint-in-persistent-me
kind: pattern
title: Tag the Origin of Every Negative Constraint in Persistent Memory
date: 2026-10-31
---

When an agent or long-running system persists negative constraints — do-not lines, holds, skips, exclusions, blocklist entries — record the provenance of each one alongside the constraint itself, and treat provenance as a first-class field rather than a comment.

HOW:

1. Define a closed set of origin tags for any persisted negative constraint. At minimum distinguish: directed by a human principal, inferred by the system (e.g., a safeguard written after an incident or failure), imported from an external policy, and temporary/experimental. Give each tag a documented authority level.

2. Require the tag at the write path. The component that validates or schema-checks memory writes must reject a negative constraint that lacks a valid origin tag. Do not rely on convention or on reviewers noticing; make the omission a hard failure at the point of persistence so an untagged constraint cannot exist.

3. Capture the tag at creation time, not retroactively. The only moment the origin is reliably known is when the constraint is written. A later reader cannot distinguish a safeguard the system invented for itself from an instruction a human gave, and will default to the stronger reading.

4. Make the resolution rule explicit at read time. When a session or run encounters a persisted negative constraint that stands in the way of an explicitly requested goal, branch on the tag: constraints with human-principal origin are honoured silently; constraints with system-inferred or imported origin are surfaced to the requester once, with the constraint text and the reason it was created, before being honoured. Ask once per session, not once per decision, so the check does not become a nag.

5. Record the outcome of that confirmation back into memory with an updated tag, so a confirmed hold becomes human-directed and stops prompting, and a rejected hold is removed or marked overridden rather than silently re-honoured next session.

6. Add expiry or review metadata to system-inferred constraints specifically. A safeguard created in response to one incident is the category most likely to outlive its cause, so give it a review date or a bounded scope at creation.

TESTS:

- Attempt to write a negative constraint with no origin tag through the normal memory path; assert the validator refuses the write and surfaces a clear error.
- Attempt a write with an origin tag outside the allowed set; assert rejection.
- Seed memory with a system-inferred constraint that conflicts with a requested goal; assert exactly one confirmation prompt is raised and the constraint is not applied before the answer.
- Seed the same scenario with a human-directed constraint; assert it is applied with no prompt.
- Confirm a prompted constraint, then re-run; assert no second prompt. Reject it, then re-run; assert it no longer blocks.

WHY THIS SHAPE: provenance decays faster than content. The text of a constraint survives indefinitely in persisted memory, while the knowledge of who imposed it and why lives only in the session that created it. Each subsequent reader inherits the constraint with its authority silently upgraded to the maximum, so a defensive guardrail the system wrote for itself ends up overriding the goals of the person it serves, and can do so for a long time before anyone with the standing to reject it happens to see it. Tagging at the write path and branching at the read path keeps that upgrade from happening, and keeps the cost of the check to a single question.
