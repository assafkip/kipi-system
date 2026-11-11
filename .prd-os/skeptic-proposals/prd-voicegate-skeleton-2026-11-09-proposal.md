# Skeptic anti-pattern proposal - prd-voicegate-skeleton-2026-11-09

Generated: 2026-11-11T23:53:20Z

## Findings the Skeptic did not catch

The reviewer flagged no accepted findings of severity blocker or major. Nothing to learn from this round.

## Skeptic Q-A pairs captured

**Q1:** What is the strongest argument against doing this?

These are fleet-wide tools changed to serve one instance. And a skeleton change does not reliably reach instance origins: consulting's origin/main missed the whole prd-os overhaul until ASK-4199 (RULE-2026-11-09-A). Answered in Proposed approach: each dependent consulting spec checks the blob on consulting origin/main before it starts.

**Q2:** What is the smallest experiment that would disprove the thesis?

For K1: delete `automation/gate_draft_hook.py` in a temp copy of consulting and write a dated draft that names a price. If that draft is refused today, the guard is not needed (consulting K1b's red test). For K8: run the band lint on one x draft with and without a manifest. If the engine argv is the same, K8 adds nothing (spec 1's red test).

**Q3:** What is the cheapest non-build alternative?

Hand-edit consulting's `settings.json`. Measured 2026-11-09: the integrity tripwire reverts unsanctioned `.claude/` edits in the running checkout, and RULE-2026-11-06-A rules out review discipline as the holder.

## How to merge (Sana, through the normal issue flow)

1. Read each finding above. The 'routed to Qx' label tells you which Skeptic question should have surfaced it.
2. Rewrite the proposed phrasing so it reads as a watched-for pattern, not as a template.
3. Append accepted anti-patterns to `plugins/prd-os/personas/skeptic.md` under '## Anti-patterns the Skeptic watches for'.
4. Open a PR so Codex review fires on the diff, then merge it. Reject a finding here by saying why in the PR; a rejection is an outcome, an unread proposal is not.
