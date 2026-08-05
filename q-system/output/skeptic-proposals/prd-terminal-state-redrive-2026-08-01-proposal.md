# Skeptic anti-pattern proposal - prd-terminal-state-redrive-2026-08-01

> **Recovered work-product — a point-in-time snapshot, not current documentation.**
> This file existed only in a dirty checkout and was recovered on 2026-08-05
> (PR #106, ASK-363). Every claim about system state was true at this document's
> own date and may not be true now. In particular, "wired" here means *merged in
> this repository*; whether the RUNNING copy loads it is a separate question that
> `q-system/.q-system/scripts/runtime-plugin-freshness.py` answers, because the
> two came apart for a full day during this very build. Read it as a record of
> what was decided and why, and verify current state against the code.

Generated: 2026-08-02T02:41:51Z

## Findings the Skeptic did not catch

### finding-1 (blocker, routed to uncategorized, class: no-known-class)

The claimed working reference implementation is false. linear-dor-drafter.py needs_dor() returns False when the description already contains 'Definition of Ready', and every needs-scope issue has a DoR (that is why it was refused). The drafter never queries labels and the string needs-scope appears zero times in it. So needs-scope is also an unconsumed dead end, the worker's Linear comment promising a re-scope is false, and the PRD's copy-the-working-pattern premise has no working pattern to copy.

**Proposed anti-pattern phrasing:**

Codex flagged this issue but it does not match any pre-defined anti-pattern class. Treat this as a candidate for a new Skeptic question or a different persona (PM, Architect, UX).

### finding-2 (blocker, routed to uncategorized, class: no-known-class)

The validator can pass without proving continuation. Checking that a consumer exists, is executable, and appears on a wiring surface proves text-level wiring only, not that the consumer reads this state, changes it, or eventually pages after failure.

**Proposed anti-pattern phrasing:**

Codex flagged this issue but it does not match any pre-defined anti-pattern class. Treat this as a candidate for a new Skeptic question or a different persona (PM, Architect, UX).

### finding-8 (blocker, routed to uncategorized, class: no-known-class)

Opt-in, project filtering, and worktrees do not adequately protect client repos (Alice, Prodigy_Gold). The dispatcher would run each repo's local ./kipi, push branches, and auto-merge, while the PRD defines no per-repo preflight for control-code version, hooks, remote identity, branch protection, credentials, dirty state, or a client-specific kill switch.

**Proposed anti-pattern phrasing:**

Codex flagged this issue but it does not match any pre-defined anti-pattern class. Treat this as a candidate for a new Skeptic question or a different persona (PM, Architect, UX).

### finding-16 (major, routed to uncategorized, class: no-known-class)

The repo cannot substantiate the claimed independent-review chain: the PRD and its source plan are both untracked, frontmatter reviewers is empty, and no engine receipt exists yet. This review is cross-model if the Claude-authorship assertion is true, but it is adversarial analysis, not proof of independent authorship nor of the PRD's live Linear measurements.

**Proposed anti-pattern phrasing:**

Codex flagged this issue but it does not match any pre-defined anti-pattern class. Treat this as a candidate for a new Skeptic question or a different persona (PM, Architect, UX).

## Skeptic Q-A pairs captured

**Q1:** What is the strongest argument against doing this?

That Piece A alone may fix most of the observed pain, and B and C are

**Q2:** What is the smallest experiment that would disprove the thesis?

Piece A shipped alone. If `needs-scope` redrives and the parked issues start

**Q3:** What is the cheapest non-build alternative?

Fix `needs_dor()` to also select on the `needs-scope` label — a few lines in

## How to merge

1. Read each finding above. The 'routed to Qx' label tells you which Skeptic question should have surfaced it.
2. Edit the proposed anti-pattern phrasing to match your voice.
3. Append accepted anti-patterns to `plugins/prd-os/personas/skeptic.md` under '## Anti-patterns the Skeptic watches for'.
4. Commit through normal git flow so Codex review fires on the diff.
