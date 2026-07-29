# Skeptic anti-pattern proposal - prd-deterministic-reading-2026-07-28

Generated: 2026-07-28T23:07:53Z

## Findings the Skeptic did not catch

Codex flagged no accepted findings of severity blocker or major. Nothing to learn from this round.

## Skeptic Q-A pairs captured

**Q1:** What is the strongest argument against doing this?

It pays 13k tokens on every session of every instance to fix a failure that

**Q2:** What is the smallest experiment that would disprove the thesis?

Run `find <instance> -type f -name "*.md" | xargs wc -l` across all 24

**Q3:** What is the cheapest non-build alternative?

Part C alone (~10 lines), plus adding the instance content dir to the existing

## How to merge

1. Read each finding above. The 'routed to Qx' label tells you which Skeptic question should have surfaced it.
2. Edit the proposed anti-pattern phrasing to match your voice.
3. Append accepted anti-patterns to `plugins/prd-os/personas/skeptic.md` under '## Anti-patterns the Skeptic watches for'.
4. Commit through normal git flow so Codex review fires on the diff.
