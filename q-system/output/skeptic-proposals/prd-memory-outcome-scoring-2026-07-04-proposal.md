# Skeptic anti-pattern proposal - prd-memory-outcome-scoring-2026-07-04

Generated: 2026-07-04T20:06:45Z

## Findings the Skeptic did not catch

### finding-1 (major, routed to uncategorized, class: no-known-class)

The PRD leaves the auto-memory data path unresolved while v1 targets q-system/memory/outcomes.jsonl, but the existing recall hooks read ~/.claude/projects/<project>/memory/*.md, so the scorer can ship against a different store than the memories being recalled.

**Proposed anti-pattern phrasing:**

Codex flagged this issue but it does not match any pre-defined anti-pattern class. Treat this as a candidate for a new Skeptic question or a different persona (PM, Architect, UX).

### finding-3 (major, routed to uncategorized, class: no-known-class)

The corroboration gate requires >= 2 distinct useful outcomes, but the event schema has no event_id, session_id, or caller identity, so duplicate writes can promote a memory to preferred.

**Proposed anti-pattern phrasing:**

Codex flagged this issue but it does not match any pre-defined anti-pattern class. Treat this as a candidate for a new Skeptic question or a different persona (PM, Architect, UX).

### finding-4 (major, routed to uncategorized, class: no-known-class)

Source-fingerprint staleness is underspecified because the sidecar stores a hash but no canonical source path or source list, making recomputation ambiguous for missing, renamed, or multi-source memories.

**Proposed anti-pattern phrasing:**

Codex flagged this issue but it does not match any pre-defined anti-pattern class. Treat this as a candidate for a new Skeptic question or a different persona (PM, Architect, UX).

### finding-5 (major, routed to uncategorized, class: no-known-class)

The earned-trust status reaches the SessionStart surface and optional MEMORY.md marker, but direct reads of the memory file still show only confidence and decay, so contested or stale status does not reach every reader.

**Proposed anti-pattern phrasing:**

Codex flagged this issue but it does not match any pre-defined anti-pattern class. Treat this as a candidate for a new Skeptic question or a different persona (PM, Architect, UX).

## Skeptic Q-A pairs captured

**Q1:** What is the strongest argument against doing this?

v1 ships the scoring engine but not the auto-capture, so with zero recorded

**Q2:** What is the smallest experiment that would disprove the thesis?

Hand-log 10-15 real outcomes across a week of actual kipi memory use, run

**Q3:** What is the cheapest non-build alternative?

Do nothing and rely on the founder correcting stale memories in-session

## How to merge

1. Read each finding above. The 'routed to Qx' label tells you which Skeptic question should have surfaced it.
2. Edit the proposed anti-pattern phrasing to match your voice.
3. Append accepted anti-patterns to `plugins/prd-os/personas/skeptic.md` under '## Anti-patterns the Skeptic watches for'.
4. Commit through normal git flow so Codex review fires on the diff.
