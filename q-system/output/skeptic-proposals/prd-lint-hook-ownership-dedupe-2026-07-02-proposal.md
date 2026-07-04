# Skeptic anti-pattern proposal - prd-lint-hook-ownership-dedupe-2026-07-02

Generated: 2026-07-02T19:44:47Z

## Findings the Skeptic did not catch

### finding-2 (major, routed to uncategorized, class: no-known-class)

Proposed test bans ANY CLAUDE_PROJECT_DIR reference in every plugin hook command — broader than the stated problem (plugin hooks invoking q-system-shipped scripts); would also fail legitimate plugin hooks that need the project path.

**Proposed anti-pattern phrasing:**

Codex flagged this issue but it does not match any pre-defined anti-pattern class. Treat this as a candidate for a new Skeptic question or a different persona (PM, Architect, UX).

## Skeptic Q-A pairs captured

**Q1:** What is the strongest argument against doing this?

The plugin wiring is a belt-and-suspenders backstop if an instance's

**Q2:** What is the smallest experiment that would disprove the thesis?

Enable kipi-core in an instance, edit a file violating voice-lint, count

**Q3:** What is the cheapest non-build alternative?

Do nothing — the lints are idempotent so correctness holds. Rejected

## How to merge

1. Read each finding above. The 'routed to Qx' label tells you which Skeptic question should have surfaced it.
2. Edit the proposed anti-pattern phrasing to match your voice.
3. Append accepted anti-patterns to `plugins/prd-os/personas/skeptic.md` under '## Anti-patterns the Skeptic watches for'.
4. Commit through normal git flow so Codex review fires on the diff.
