# Skeptic anti-pattern proposal - prd-reorg-stale-ref-remediation-2026-07-06

Generated: 2026-07-06T22:40:47Z

## Findings the Skeptic did not catch

### finding-6 (major, routed to uncategorized, class: no-known-class)

The old-to-new move map is duplicated by hand in reorg-stale-ref-audit.py instead of derived from persona-reorg.py or manifests, which leaves the cross-cutting no-stale-ref invariant vulnerable to drift.

**Proposed anti-pattern phrasing:**

Codex flagged this issue but it does not match any pre-defined anti-pattern class. Treat this as a candidate for a new Skeptic question or a different persona (PM, Architect, UX).

### finding-7 (major, routed to uncategorized, class: no-known-class)

The rollback plan relies on .persona-reorg.bak files, but existing backups are explicitly unresolved and _bak will not refresh them, so remediation rollback can restore stale pre-reorg content instead of the current pre-remediation state.

**Proposed anti-pattern phrasing:**

Codex flagged this issue but it does not match any pre-defined anti-pattern class. Treat this as a candidate for a new Skeptic question or a different persona (PM, Architect, UX).

### finding-8 (major, routed to uncategorized, class: no-known-class)

The cross-project remediation mode has no required unit or fixture test, so the riskiest new behavior is only covered indirectly by the current audit.

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
