---
id: prd-spillover-gate-2026-06-20
title: Spillover gate: no out-of-scope finding is ever silently dropped
status: archived
created_at: 2026-06-20T05:42:37Z
updated_at: 2026-06-30T22:26:09Z
owner: assafkip
findings_path: .prd-os/findings/prd-spillover-gate-2026-06-20-findings.jsonl
---

# Spillover gate: no out-of-scope finding is ever silently dropped

## Problem

When prd-os/kipi-dsse/fable work surfaces an issue that is OUT OF SCOPE for the
current issue, the issue is lost. Two leak paths, both observed repeatedly:

1. **Findings marked `deferred` in triage are terminal.** The findings schema
   enum is `pending|accepted|rejected|deferred`; a `deferred` finding needs only
   a rationale and the PRD advances to `approved`. Nothing tracks it afterward.
2. **Adjacent issues mentioned in prose vanish entirely.** The standing rule was
   "mention adjacent issues after completing, do not bundle." A mention in chat
   is not tracked anywhere; once the message scrolls, it is gone.

The operator has ADHD and will not manually revisit a backlog that lives only in
chat. "Tell the founder" is not tracking. The result: real defects (the Obsidian
export + CLI digest archive-filter gaps flagged during the QEP build; others)
were named once and never resolved, with no durable record they existed.

## Goals

- A durable, append-only ledger (`.prd-os/spillover.jsonl`) is the single home
  for every out-of-scope finding. Capture is a file write, never prose.
- A `deferred` triage disposition AUTOMATICALLY creates an open spillover item
  (deterministic; the operator cannot defer-and-forget).
- The standing repo gate (`prd_runner.py gates run`, the "no bypass remains"
  re-proof that must exit 0) FAILS while any spillover item is `open`. Forgetting
  an item = a permanently red gate. This is the ADHD-proof property.
- A spillover item can only flip to `resolved` by pointing at a real prd-os/dsse
  issue that is itself closed (has a close receipt / green gate). You cannot
  hand-clear it; you must actually build and test the fix.
- The fable-discipline lint hook BLOCKS output that uses deferral language
  ("out of scope", "adjacent", "follow-up", "defer", "future work") without a
  matching ledger write, and the checklist requires the capture.
- Issue/PRD closeout REPORTS each spillover item, the issue that resolved it, the
  fix, and how it affected the system.

## Non-goals

- `rejected` findings stay terminal (with rationale). "Out of scope" means a real
  issue deferred to later, not an invalid/duplicate/won't-do finding. Forcing
  every rejected finding to be "fixed" would be wrong.
- No auto-fixing. The gate forces the fix to be DONE and TRACKED; it does not
  write the fix. A human/agent still builds each spillover item through the normal
  reproducer-first issue flow.
- No change to the meaning of `accepted` (fixed in this PRD) or `pending`.

## Proposed approach

```
out-of-scope found ---> spillover.jsonl (status: open)        [capture]
   (deferred triage, prose deferral via `spillover add`, fable-lint enforced)

gates run ---> registered gates + spillover check             [gate]
   any open spillover item  => RED, exit 1  (standing, can't be forgotten)

spillover resolve <id> --resolution-ref <issue-id>            [resolution]
   verifies the referenced issue is CLOSED (receipt/green gate),
   else refuses. Only then flips item to resolved.

closeout ---> prints spillover items + their resolution + system impact  [report]
```

Reuse existing infra: the gate registry pattern (`gates.jsonl`, append-only,
idempotent, fail-closed) is the model for `spillover.jsonl`. The spillover check
is embedded directly in `cmd_gates` "run" (repo-global, not per-issue), so it
runs every time the standing re-proof runs.

## Risks and rollback

- Risk: false-positive capture from the fable lint (flagging the words
  "out of scope" in unrelated prose). Mitigation: the lint requires the deferral
  to be a CLAIM about the change under work; scope the regex + allow an explicit
  `# spillover-skip` marker (one per file) consistent with the other lint hooks.
- Risk: the standing gate goes red and blocks unrelated closeouts. That is the
  intended behavior; the escape is to resolve the item, not to bypass. A genuine
  false item can be `spillover resolve --void <reason>` (recorded, not deleted).
- Rollback: the feature is additive (new ledger, new subcommands, one new gate
  check). Remove the `gates run` spillover hook to disable enforcement; the
  ledger remains as a record.

## Persona Review

### Skeptic

Q1: What is the strongest argument against doing this?
A1: A standing red gate could become a nag that gets routinely bypassed, like a
flaky test. Counter: resolution requires a closed issue (cheap when the item is
small), and `--void` with a recorded reason exists for genuine non-items, so the
honest path is always cheaper than bypassing.

Q2: What is the smallest experiment that would disprove the thesis?
A2: Mark a finding `deferred`, run `gates run`, and confirm it exits non-zero
with the item named. If a deferred finding does not turn the gate red, the
capture-to-gate wiring is broken.

Q3: What is the cheapest non-build alternative?
A3: A markdown TODO list. Rejected: it is not deterministic, not gated, and
relies on the operator revisiting it (the exact failure this fixes).

## Issues

<!--
LEGACY RECORD (repaired 2026-06-30, spillover sp-cd50b062): this PRD predates the
spine-native manifest (it is id-keyed, not finding_id-keyed) and its 4 planned
issue specs were never materialized on disk -- the spillover feature shipped
DIRECTLY, outside the split flow. The work is live and covered by passing tests:
  - plugins/prd-os/tests/test_spillover.py (ledger + standing gate) PASS
  - plugins/prd-os/tests/test_deferred_spillover.py (deferred auto-creates) PASS
  - plugins/kipi-core/skills/fable-discipline/scripts/test_fable_discipline_lint.py PASS
  - .claude/rules/no-orphan-findings.md (always-on capture rule) present + propagated
The phantom manifest is emptied so this legacy PRD can reach a terminal (archived)
state; the feature it describes is in production.
-->

```json
[]
```
