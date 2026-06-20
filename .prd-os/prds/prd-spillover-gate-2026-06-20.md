---
id: prd-spillover-gate-2026-06-20
title: Spillover gate: no out-of-scope finding is ever silently dropped
status: idea
created_at: 2026-06-20T05:42:37Z
updated_at: 2026-06-20T05:42:37Z
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

```json
[
  {
    "id": "spill-01-ledger-gate",
    "title": "Spillover ledger + standing gate: add/list/resolve/check in prd_runner; gates run fails while any item is open",
    "priority": "p1",
    "allowed_files": [
      "plugins/prd-os/scripts/prd_runner.py",
      "plugins/prd-os/tests/test_spillover.py"
    ],
    "required_checks": [
      "python3 -m pytest -q plugins/prd-os/tests/test_spillover.py",
      "python3 -m pytest -q plugins/prd-os/tests"
    ],
    "bypass_check": "python3 -m pytest -q plugins/prd-os/tests/test_spillover.py",
    "acceptance": "prd_runner.py gains `spillover add|list|resolve|check`. `add` appends an open item to .prd-os/spillover.jsonl (append-only, idempotent by id). `check` exits 1 if any item is open, 0 otherwise. `resolve <id> --resolution-ref <issue-id>` refuses unless the referenced issue is closed (close receipt or registered green gate); `--void <reason>` records a non-item without a fix. `cmd_gates` 'run' invokes the spillover check and reports RED + non-zero exit while any item is open. Reproducer (a deferred/open item turning gates run red, then green after resolve) shown failing first."
    },
  {
    "id": "spill-02-deferred-feeds",
    "title": "A deferred triage disposition auto-creates an open spillover item",
    "priority": "p1",
    "allowed_files": [
      "plugins/prd-os/scripts/findings_writer.py",
      "plugins/prd-os/tests/test_deferred_spillover.py"
    ],
    "required_checks": [
      "python3 -m pytest -q plugins/prd-os/tests/test_deferred_spillover.py",
      "python3 -m pytest -q plugins/prd-os/tests"
    ],
    "bypass_check": "python3 -m pytest -q plugins/prd-os/tests/test_deferred_spillover.py",
    "acceptance": "When a finding's disposition is set to `deferred`, an open spillover item is created in .prd-os/spillover.jsonl linking back to the finding id + PRD id (idempotent: re-deferring the same finding does not duplicate). `rejected` does NOT create a spillover item. Reproducer (defer a finding, assert spillover item exists + gates run goes red) shown failing first."
  },
  {
    "id": "spill-03-fable-capture",
    "title": "fable-discipline: lint blocks deferral language with no ledger write; checklist + SKILL require capture",
    "priority": "p1",
    "allowed_files": [
      "plugins/kipi-core/skills/fable-discipline/scripts/fable-discipline-lint.py",
      "plugins/kipi-core/skills/fable-discipline/scripts/test_fable_discipline_lint.py",
      "plugins/kipi-core/skills/fable-discipline/SKILL.md",
      "plugins/kipi-core/skills/fable-discipline/references/checklist.md"
    ],
    "required_checks": [
      "python3 plugins/kipi-core/skills/fable-discipline/scripts/test_fable_discipline_lint.py"
    ],
    "bypass_check": "python3 plugins/kipi-core/skills/fable-discipline/scripts/test_fable_discipline_lint.py",
    "acceptance": "The fable-discipline-lint hook detects out-of-scope/deferral language about the change under work and blocks (exit 2) unless a spillover ledger entry exists or an explicit `# spillover-skip` marker is present. SKILL.md gains a capture rule; checklist.md gains a 'every out-of-scope finding written to spillover.jsonl' line. Negative self-test (deferral language with no ledger entry FAILS the lint) shown first."
  },
  {
    "id": "spill-04-report-wire-docs",
    "title": "Closeout reports spillover resolution + system impact; document + auto-fire the flow",
    "priority": "p1",
    "allowed_files": [
      "plugins/prd-os/commands/prd-archive.md",
      "plugins/prd-os/commands/prd-triage.md",
      "plugins/prd-os/skills/prd-os/SKILL.md",
      "plugins/prd-os/README.md",
      "plugins/prd-os/CHANGELOG.md",
      "plugins/prd-os/.claude-plugin/plugin.json",
      "plugins/kipi-dsse/commands/issue-closeout.md",
      ".claude/rules/no-orphan-findings.md"
    ],
    "required_checks": [
      "python3 -m pytest -q plugins/prd-os/tests",
      "test -f .claude/rules/no-orphan-findings.md"
    ],
    "bypass_check": "test -f .claude/rules/no-orphan-findings.md",
    "acceptance": "issue-closeout + prd-archive instruct printing every spillover item touched by the work, the resolving issue, the fix, and the system impact. prd-triage documents that `deferred` creates a spillover item. prd-os SKILL.md documents the spillover lifecycle. A new ENFORCED rule `.claude/rules/no-orphan-findings.md` (auto-loaded, propagates via kipi update) makes 'capture every out-of-scope finding to spillover.jsonl' always-on. README template/feature list + CHANGELOG + plugin.json version bumped."
  }
]
```
