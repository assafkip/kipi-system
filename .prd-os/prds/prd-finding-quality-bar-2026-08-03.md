---
id: prd-finding-quality-bar-2026-08-03
title: Finding Quality Bar
status: draft
created_at: 2026-08-03T07:10:04Z
updated_at: 2026-08-03T07:11:38Z
owner: assafkipnis
reviewers: []
findings_path: .prd-os/findings/prd-finding-quality-bar-2026-08-03-findings.jsonl
---

# Finding Quality Bar

Sequel to `prd-spillover-gate-2026-06-20` (archived). That PRD built the ledger
and the gate, and named its ADHD-proof property: *"the standing repo gate FAILS
while any spillover item is open. Forgetting an item = a permanently red gate."*

The property held mechanically and failed in practice. `gates run` does exit 1
when RED. **Nothing calls it.** Grepped 2026-08-03 across `.claude/settings.json`,
`lefthook.yml`, `.github`: zero hits. The only mentions of `gates run` are prose
inside `.claude/rules/*.md`. A permanently red gate nobody runs is a green gate.

## Problem

Capture was made frictionless and resolution was not.

**Spillover ledger (kipi-system), measured 2026-08-03:**

| | |
|---|---|
| open | 476 |
| resolved, all time | 75 |
| captured 2026-08-01 to 08-03 | 151 (~50/day) |
| names no file, no test, no command | 82 |
| names a file, no named path resolves (single-root check) | 209 |
| near-duplicate pairs | 1 |

The pile is not noise. One duplicate pair in 476. These are distinct findings
arriving faster than anyone resolves them.

**Root cause: no bar at the write path.** `cmd_spillover` accepts any string as
`--desc`. "We should also look at X" is recorded with the same weight as a
finding carrying a file, a line, and a failing command.

**Linear board:**

| | |
|---|---|
| active issues | 204 |
| lacking `## Definition of Ready` | 137 |
| of those, description under 120 chars | 0 |
| median description length | 1,341 chars (min 529) |

The board is NOT full of half issues. It is full of real issues waiting on
`linear-dor-drafter.py`, which runs `--limit 8` nightly with an unsorted batch,
no cursor, and leaves a failed draft in `todo`. A persistently-failing head is
re-attempted nightly and the tail never runs. The count went 80 -> 87 -> 93 -> 137.

**Three defects hide the ledger from its only consumer.**
`fleet-health-daily.py detect_open_spillover`:
1. runs with `cwd=REPO_ROOT` (kipi-system), so every other repo's ledger is invisible
2. scrapes stdout with `r"\[open\]\s+(sp-[0-9a-f]{8})"`, which never matches `defer-*` ids
3. emits one rollup capped at 25, collapsing 476 findings into a number

**The ledger is not one ledger.** `.prd-os/spillover.jsonl` is gitignored
(`*.jsonl`), so every worktree gets its own copy. This repo has 88 registered
worktrees; 26 hold 71 open findings absent from the main checkout (`sp-10ea7b66`).
Any count taken from one checkout is wrong.

## Goals

- A capture with no verifiable anchor is REFUSED at write time.
- The 82 anchorless rows are removed, each with a recorded reason.
- Findings whose subject no longer exists are proposed for removal by a script
  resolving paths across every fleet root, never by a single-root guess.
- The DoR drafter reaches the tail of its queue, and closes an issue it cannot
  spec from real sources rather than leaving it in `todo` forever.
- One ledger across worktrees.
- `detect_open_spillover` reports every repo and every id shape.

## Non-goals

- Auto-filing spillover to Linear (ASK-321). Blocked until the ledger is one
  ledger and the drafter keeps up. Filing into a starved queue moves the pile.
- Bulk-fixing the 394 anchored findings. This PRD makes them countable and
  removes the dead ones; it does not resolve the live ones.
- Changing `linear-worker.sh`'s refusal to work a DoR-less issue. That refusal
  is correct and is why the queue is visible at all.

## Proposed approach

Bar first, drain second.

**The anchor rule.** A capture must carry at least one of:
- a file path that resolves under a known fleet root
- a command plus its actual output
- a named test

Refusal names which anchor is missing. `--force` writes `anchor: none` on the row
so unbarred captures stay countable — the same shape as the `[no-issue: reason]`
hatch in `linear-issue-ref-check.py`, which appends to `linear-bypass.jsonl`
rather than skipping silently.

**Close-on-unspeccable belongs in the drafter, not a sweep.** When the drafter
cannot write a DoR from real sources it currently leaves the issue in `todo`. It
should close it with the reason. A DoR invented without sources is worse than no
issue: it aims the autonomous worker at fabricated requirements.

## Alternatives considered

- **Drain first, bar later.** Rejected: 50/day keeps arriving during the drain,
  so the count never converges and the work is unmeasurable.
- **Bar + auto-file to Linear in one change.** Rejected: the ledger is 27 ledgers
  and the DoR queue is 137 behind. Filing now relocates the pile into a queue
  that structurally cannot absorb it.
- **A sweep script that closes unspeccable Linear issues.** Rejected in favour of
  putting the rule in the drafter. A second writer against the same board is the
  divergent-copy failure this repo already has three instances of.
- **Warn instead of refuse on capture.** Rejected: a warning is what the current
  system already effectively is, and it produced 476 items.

## Scenarios

- **Anchorless capture.** An agent finds something adjacent and runs
  `spillover add --desc "we should also look at the retry path"`. The runner
  exits non-zero naming the missing anchor. The agent either supplies a file or
  a failing command, or uses `--force`, which records `anchor: none`.
- **Legitimate capture mid-task.** An agent hits a real defect in
  `capability-gate.py:212`. The path resolves, the row is written with
  `anchor: file`, and nothing changes for the agent.
- **Validator proposes, human-reviewed batch disposes.** `spillover-validate.py`
  resolves every named path across all fleet roots, prints a proposed-void list
  with a reason per row, and writes nothing. A separate invocation applies them.
- **Unspeccable Linear issue.** The drafter reads an issue, finds no real source
  for a DoR, and closes it with the reason instead of leaving it in `todo`.

## Resolved decisions

- **Bulk void without per-row founder approval.** Decided: allowed. Rationale:
  founder-directed 2026-08-03, *"its okay to delete and write down why."* The
  ledger is append-only so voided text survives; nothing is physically removed.
- **The board is not the problem.** Decided: do not apply close-on-sight to the
  137 no-DoR issues as a sweep. Rationale: measured median description 1,341
  chars, zero under 120. They are real issues waiting on a starved drafter.
- **`--force` stays.** Decided: keep an escape hatch, make it countable.
  Rationale: a bar with no hatch gets removed the first time it blocks real work;
  `linear-issue-ref-check.py` already proves the countable-hatch shape works.

## Risks and rollback

- **Bulk void deletes real findings.** Mitigated: validator proposes, a separate
  step disposes, reason recorded per row, ledger append-only.
- **Un-ignoring `spillover.jsonl` changes git behavior across 88 worktrees.**
  Highest blast radius here. Sequenced behind its own issue, late.
- **The bar blocks a legitimate capture mid-task.** `--force` exists and stays
  countable.
- **`anchor: none` becomes the default escape.** Mitigated by making the
  forced-row count printable, so drift is visible rather than assumed.

## Open questions

- Whether the anchor rule should also apply to `defer-*` rows created
  automatically by `findings_writer`. Those carry a finding id but often no file.

## Persona Review

### Skeptic

Q1: What is the strongest argument against doing this?
A1: The 476 findings are genuinely real (one duplicate pair in 476), so a bar
that would have refused some of them destroys real signal. The counter: 82 carry
no anchor at all, and an unverifiable finding is indistinguishable from noise no
matter how real it felt when written.

Q2: What is the smallest experiment that would disprove the thesis?
A2: Take 20 anchorless rows and try to act on them cold. If a majority can be
resolved without their author, the anchor rule is too strict.

Q3: What is the cheapest non-build alternative?
A3: Run `gates run` from a SessionStart hook — one line, surfaces the red gate
that already exists. It does not stop inflow, so it is a complement, not a
substitute.

## Issues

```json
[]
```
