# Skeptic anti-pattern proposal - prd-morning-brief-learns-2026-09-01

Generated: 2026-09-02T04:11:09Z

## Findings the Skeptic did not catch

### finding-1 (blocker, routed to Q3, class: empty-non-goals-class)

Issue mbl-friction-artifact claims the product/roadmap boundary is a hard gate, but enforcement trusts the friction author's declared target field. A product proposal can be labeled target=rule and pass both checks. This does not enforce the Non-goals invariant and can allow the self-improvement loop to make product decisions.

**Proposed anti-pattern phrasing:**

When Q3 is answered with 'no alternative exists' or scope is left implicit, treat the answer as unanswered and re-ask with concrete non-build paths (template change, checklist, founder discipline).

### finding-2 (major, routed to uncategorized, class: no-known-class)

Issues mbl-owed-narrows-to-three, mbl-collector-isolation, mbl-unknown-term-detector, and mbl-board-writer all overlap on q-system/.q-system/scripts/morning-brief.py and test_morning_brief.py. This violates the rubric's atomic-decomposition rule and creates serialization risk between changes to SECTIONS, collect_all(), build(), and main().

**Proposed anti-pattern phrasing:**

Codex flagged this issue but it does not match any pre-defined anti-pattern class. Treat this as a candidate for a new Skeptic question or a different persona (PM, Architect, UX).

### finding-3 (major, routed to uncategorized, class: no-known-class)

Issue mbl-friction-artifact allows plugins/kipi-core/skills/*/SKILL.md while mbl-improve-skill separately owns plugins/kipi-core/skills/improve/SKILL.md. The wildcard creates an explicit allowed_files overlap and gives one issue fleet-wide authority to modify every skill for an unrelated changelog requirement.

**Proposed anti-pattern phrasing:**

Codex flagged this issue but it does not match any pre-defined anti-pattern class. Treat this as a candidate for a new Skeptic question or a different persona (PM, Architect, UX).

### finding-4 (blocker, routed to uncategorized, class: no-known-class)

Proposed approach item 4 and Scenario 'Board token missing' are internally impossible as written. The board operation runs only after Slack has answered, so its failure cannot appear in the Slack brief that was already sent. The PRD must define whether board status belongs in the brief, a later Slack message, logs, or only the receipt.

**Proposed anti-pattern phrasing:**

Codex flagged this issue but it does not match any pre-defined anti-pattern class. Treat this as a candidate for a new Skeptic question or a different persona (PM, Architect, UX).

### finding-5 (major, routed to uncategorized, class: no-known-class)

Issue mbl-board-writer does not define stable item identity or reconciliation. Rewriting top-of-mind from today's three source items can re-add an item the founder manually moved to this week or inbox, despite acceptance requiring moved items to stay moved. A test that merely asserts other blocks are not directly edited will not catch this semantic overwrite.

**Proposed anti-pattern phrasing:**

Codex flagged this issue but it does not match any pre-defined anti-pattern class. Treat this as a candidate for a new Skeptic question or a different persona (PM, Architect, UX).

### finding-6 (major, routed to uncategorized, class: no-known-class)

Issue mbl-board-writer makes real read-back proof conditional on the founder token existing, while the Goals require read-back that proves the write landed. This permits the issue to close with only a fake opener and leaves the production credential, page permissions, block structure, and launchd access unverified.

**Proposed anti-pattern phrasing:**

Codex flagged this issue but it does not match any pre-defined anti-pattern class. Treat this as a candidate for a new Skeptic question or a different persona (PM, Architect, UX).

### finding-7 (major, routed to uncategorized, class: no-known-class)

Issue mbl-draft-vs-sent-producer does not define how a local draft is matched to a Gmail sent message. Subject reuse, replies, multiple recipients, edited subject lines, and multiple drafts can produce a plausible but incorrect pair, causing false voice-learning data to be persisted.

**Proposed anti-pattern phrasing:**

Codex flagged this issue but it does not match any pre-defined anti-pattern class. Treat this as a candidate for a new Skeptic question or a different persona (PM, Architect, UX).

### finding-8 (major, routed to uncategorized, class: no-known-class)

Issue mbl-draft-vs-sent-producer persists full original and sent email bodies into copy_edits without specifying a redacted, whitelisted projection, retention policy, or recipient-based necessity boundary. This matches gap class 11: raw request-derived content becomes durable and may later be exported through proposal files.

**Proposed anti-pattern phrasing:**

Codex flagged this issue but it does not match any pre-defined anti-pattern class. Treat this as a candidate for a new Skeptic question or a different persona (PM, Architect, UX).

### finding-9 (major, routed to uncategorized, class: no-known-class)

Issue mbl-draft-vs-sent-producer combines three independently failing units: Gmail pairing and database insertion, route-overrides behavior, and launchd registration. Its acceptance does not state what triggers draft-vs-sent.py itself, so the new producer may remain dead wiring while only the downstream weekly route is scheduled.

**Proposed anti-pattern phrasing:**

Codex flagged this issue but it does not match any pre-defined anti-pattern class. Treat this as a candidate for a new Skeptic question or a different persona (PM, Architect, UX).

### finding-11 (major, routed to uncategorized, class: no-known-class)

Issue mbl-improve-skill requires searching a consulting corpus under ~/projects/consulting while q-consult/** is disallowed and the feature is meant to fan out across 25 instances. The behavior depends on a workstation-specific sibling checkout, and no contract defines missing, unreadable, stale, or differently located corpora.

**Proposed anti-pattern phrasing:**

Codex flagged this issue but it does not match any pre-defined anti-pattern class. Treat this as a candidate for a new Skeptic question or a different persona (PM, Architect, UX).

### finding-12 (major, routed to uncategorized, class: no-known-class)

Issue mbl-improve-skill says it must never return adopt for product ideas, but acceptance tests only one phrase, 'sell a Notion template', and specifies no deterministic scope classifier or fail-closed behavior. Paraphrased product, pricing, publishing, or client-advice prompts can bypass the invariant.

**Proposed anti-pattern phrasing:**

Codex flagged this issue but it does not match any pre-defined anti-pattern class. Treat this as a candidate for a new Skeptic question or a different persona (PM, Architect, UX).

### finding-13 (major, routed to uncategorized, class: no-known-class)

Issue mbl-unknown-term-detector defines unknowns as proper nouns and capitalized multi-word terms absent from canonical Markdown, but provides no normalization, allowlist, confidence threshold, or precision target. Sentence starts, attendee names, email signatures, and ordinary branded terms will dominate the five-item cap and make the section systematically noisy.

**Proposed anti-pattern phrasing:**

Codex flagged this issue but it does not match any pre-defined anti-pattern class. Treat this as a candidate for a new Skeptic question or a different persona (PM, Architect, UX).

### finding-17 (major, routed to uncategorized, class: no-known-class)

Risks and rollback says the five fleet scripts are inert without their plist installed, but friction-note.sh is explicitly invoked manually and notion_board.py is wired into the existing 07:00 morning run. The rollback description also ignores modifications to morning-brief.py, CLAUDE.md, README.md, skill files, tests, and the plan file. Operators following the stated file-deletion rollback would leave active wiring behind.

**Proposed anti-pattern phrasing:**

Codex flagged this issue but it does not match any pre-defined anti-pattern class. Treat this as a candidate for a new Skeptic question or a different persona (PM, Architect, UX).

## Skeptic Q-A pairs captured

**Q1:** What is the strongest argument against doing this?

That self-improvement loops are theatre (Carson: "kind of a joke" with

**Q2:** What is the smallest experiment that would disprove the thesis?

Run `weekly-improve.sh` for four Mondays. If zero friction lines are ever

**Q3:** What is the cheapest non-build alternative?

Keep writing friction into lessons by hand via `lesson-note.sh`. Rejected

## How to merge

1. Read each finding above. The 'routed to Qx' label tells you which Skeptic question should have surfaced it.
2. Edit the proposed anti-pattern phrasing to match your voice.
3. Append accepted anti-patterns to `plugins/prd-os/personas/skeptic.md` under '## Anti-patterns the Skeptic watches for'.
4. Commit through normal git flow so Codex review fires on the diff.
