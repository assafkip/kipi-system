---
id: prd-prompt-only-guard-stderr-2026-07-02
title: Prompt Only Guard Stderr
status: archived
created_at: 2026-07-02T23:13:41Z
updated_at: 2026-07-02T23:20:51Z
owner: assafkipnis
reviewers: []
findings_path: .prd-os/findings/prd-prompt-only-guard-stderr-2026-07-02-findings.jsonl
codex_reviewed_at: 2026-07-02T23:15:52Z
---

<!-- prompt-only-enforcement-skip: this PRD documents the guard itself; its
     vocabulary (hook, block, enforcement) trips mention-vs-claim FPs. The
     enforcement here IS executable: test-prompt-only-enforcement-guard-stderr.sh -->

# Prompt-only-enforcement-guard: block message must reach stderr

## Problem

Observed live 2026-07-02 (this session): the `prompt-only-enforcement-guard.py`
PostToolUse hook blocked a Write with exit 2 but printed its reason as JSON to
STDOUT (`print(json.dumps({"message": ...}))`, old line 268). Claude Code feeds
only STDERR back to the model on exit 2, so the block surfaced as
`"No stderr output"` — the model (and founder) got a reasonless wall. Every
block this hook has ever issued was silent. Captured as spillover sp-cd530cc7.

## Goals

- On block: plain-text message on stderr, exit 2, stdout clean (the
  skill-hook-pairing exit-code contract).
- A regression test pins the contract and was shown failing against the old
  stdout form (negative self-test).

## Non-goals

- No change to detection patterns, scan windows, target-file scoping, or the
  skip marker.
- No audit of other hooks' stderr discipline (only this hook was observed
  violating; a fleet sweep would be its own item if one is caught).

## Proposed approach

Shipped in commit 2c14139 (this PRD wraps it in the gate retroactively so
sp-cd530cc7 can resolve):

- `q-system/.q-system/scripts/prompt-only-enforcement-guard.py`: block path
  prints the message to stderr as plain text; scar comment cites sp-cd530cc7.
- `q-system/.q-system/scripts/test/test-prompt-only-enforcement-guard-stderr.sh`:
  violation fixture must exit 2 with `BLOCK:` on stderr and NOTHING on stdout;
  clean fixture must pass. Run red against the pre-fix script, green after.

## Alternatives considered

- **Keep JSON on stdout and also print stderr** — Rejected: exit-2 stdout JSON
  is dead output in the PostToolUse contract; keeping it invites the next
  reader to assume it does something.
- **Emit hookSpecificOutput JSON (warn-style) instead of exit 2** — Rejected:
  this hook is a blocker by design (q-system/CLAUDE.md rule 3); advisory
  context would let prompt-only enforcement claims land.

## Scenarios

- **Blocked write.** Agent writes a doc claiming "enforced by the skill" with
  no executable blocker; hook exits 2; the model sees the BLOCK message with
  file:line on stderr and names/adds a deterministic blocker.
- **Clean write.** Doc names the hook/test that enforces the rule; hook exits
  0; nothing printed.

## Resolved decisions

- **stderr, plain text.** Decided: match `token-guard.py`'s `block()` shape.
  Rationale: one contract across all blocking hooks; stderr is the only channel
  Claude Code relays on exit 2.

## Risks and rollback

Blast radius is one print statement in one hook; no consumer parsed the old
stdout JSON (nothing could — it was invisible). Rollback = revert 2c14139.

## Open questions

- None.

### Skeptic

Q1: What is the strongest argument against doing this?
A1: It's a 2-line fix already shipped; the gate ceremony costs more than the
fix. Counter: the spillover ledger refuses hand-clearing by design, and the
receipt registers the regression test as a permanent gate.

Q2: What is the smallest experiment that would disprove the thesis?
A2: Re-run the live probe (stdin PostToolUse event on a violating file) and
show the message arriving on stderr — done this session, exit=2 with BLOCK
text on stderr, stdout empty.

Q3: What is the cheapest non-build alternative?
A3: Void sp-cd530cc7. Rejected: the defect is real and observed; voiding would
be a false record.

<!--
## Persona Review (optional, fill in before /prd-review)

Phase 0 of the prd-os planning-personas experiment (PRD prd-planning-personas-2026-05-13).
For non-trivial PRDs, answer the three Skeptic questions below before invoking /prd-review.
Brief answers are fine. The goal is to force one round of adversarial thinking before Codex.

### Skeptic

Q1: What is the strongest argument against doing this?
A1:

Q2: What is the smallest experiment that would disprove the thesis?
A2:

Q3: What is the cheapest non-build alternative?
A3:

When done with these questions, uncomment this section and move it to live just before `## Issues` below.
-->

## Issues

<!--
After review and approval, populate the fenced JSON block below. The manifest is
read by TWO consumers and every entry must satisfy both:
  - `prd_split.py` materializes one issue spec per entry (needs `id`).
  - the approval gate proves every ACCEPTED finding is covered by an entry (needs
    `finding_id` + a `bypass_check`). One entry per accepted finding.

Required keys per entry (spine-native -- both consumers):
  - id (kebab-case, unique across the repo)            -- prd_split.py
  - finding_id (the accepted finding it covers, e.g. "finding-1") -- approval gate
  - title (non-empty string)
  - allowed_files (non-empty list of glob patterns)
  - required_checks (non-empty list, e.g. ["pytest -q"]). The stop-gate checks
    three receipts (verified, reviewed, findings_triaged); they are meaningless
    unless the spec documents what must be verified, so an empty list is rejected.
  - bypass_check (a command proving no bypass remains) OR
    bypass_exempt: "<reason>"                          -- spine contract

Optional keys:
  - priority (default p1)
  - disallowed_files, required_reviews, acceptance

Authoring a manifest with `id` but no `finding_id` (the pre-spine shape) is
rejected at approve. The template-vs-runner contract test enforces this list.
-->

```json
[
  {
    "id": "prompt-only-guard-stderr",
    "finding_id": "finding-1",
    "title": "prompt-only-enforcement-guard block message must reach stderr (sp-cd530cc7)",
    "priority": "p2",
    "allowed_files": [
      "q-system/.q-system/scripts/prompt-only-enforcement-guard.py",
      "q-system/.q-system/scripts/test/test-prompt-only-enforcement-guard-stderr.sh"
    ],
    "required_checks": [
      "bash q-system/.q-system/scripts/test/test-prompt-only-enforcement-guard-stderr.sh"
    ],
    "bypass_check": "bash q-system/.q-system/scripts/test/test-prompt-only-enforcement-guard-stderr.sh"
  }
]
```
