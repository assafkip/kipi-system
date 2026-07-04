# Skeptic anti-pattern proposal - prd-accept-rate-metric-2026-06-15

Generated: 2026-06-15T23:53:50Z

## Findings the Skeptic did not catch

### finding-1 (blocker, routed to uncategorized, class: no-known-class)

The required check `python3 q-system/.q-system/scripts/accept-rate.py --selftest` does not currently pass; it exits 1 with FileNotFoundError for no usable temporary directory, so the PRD's acceptance claim that selftest passes is false in this environment.

**Proposed anti-pattern phrasing:**

Codex flagged this issue but it does not match any pre-defined anti-pattern class. Treat this as a candidate for a new Skeptic question or a different persona (PM, Architect, UX).

## Skeptic Q-A pairs captured

**Q1:** What is the strongest argument against doing this?

(missing or skipped)

**Q2:** What is the smallest experiment that would disprove the thesis?

(missing or skipped)

**Q3:** What is the cheapest non-build alternative?

(missing or skipped)

## How to merge

1. Read each finding above. The 'routed to Qx' label tells you which Skeptic question should have surfaced it.
2. Edit the proposed anti-pattern phrasing to match your voice.
3. Append accepted anti-patterns to `plugins/prd-os/personas/skeptic.md` under '## Anti-patterns the Skeptic watches for'.
4. Commit through normal git flow so Codex review fires on the diff.
