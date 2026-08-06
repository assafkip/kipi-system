---
id: prd-spillover-current-state-2026-07-24
title: Spillover Current State
status: approved
created_at: 2026-07-24T21:25:00Z
updated_at: 2026-07-24T21:14:34Z
owner: senior-staff
reviewers: []
findings_path: .prd-os/findings/prd-spillover-current-state-2026-07-24-findings.jsonl
codex_reviewed_at: 2026-07-24T21:14:11Z
---

# Spillover Current State

## Problem

The spillover ledger is append-only and the runner folds records by ID using
last file occurrence [`plugins/prd-os/scripts/prd_runner.py:951-971`]. Invalid
JSON is silently skipped [`plugins/prd-os/scripts/prd_runner.py:961-964`].
Resolution verifies only `status: closed` in an issue frontmatter
[`plugins/prd-os/scripts/prd_runner.py:982-1048`], not the issue's closeout
receipt. `gates run` treats every effective open item as one undifferentiated
red group [`plugins/prd-os/scripts/prd_runner.py:1055-1114`].

A 2026-07-24 deterministic fold after this program's two valid deferrals found
73 events, 53 IDs, and 33 effective open items: 22 minor, 3 major, 1 high, 4
low, and 3 medium. Existing tests cover basic last-write-wins, open-gate,
resolve, void, and deferral behavior
[`plugins/prd-os/tests/test_spillover.py:58-123`,
`plugins/prd-os/tests/test_deferred_spillover.py:70-102`], but not invalid
events, stale status, receipt mismatch, severity changes, or pre-existing
versus new debt.

## Goals

- Build one deterministic latest-event fold by ID.
- Preserve append-only history.
- Close, supersede, or void stale items through new events.
- Correct severity through new events only.
- Require closure receipts that point to closed issues and verified closeout
  records.
- Separate actionable open work from historical scars.
- Make `gates run` identify pre-existing debt separately from new debt.
- Test duplicate IDs, stale status, invalid resolution references, and severity
  changes.

## Non-goals

- Editing or deleting prior spillover events.
- Automatically claiming an old item is fixed.
- Creating product fixes for every current spillover item in this PRD.
- Treating historical scars as actionable open work after valid closure.

## Proposed approach

1. Define a versioned event schema with ID, event type, status, severity,
   source, description, timestamp, and optional prior-event hash. Fold by file
   order per ID and validate every event. Invalid JSON, schema, or transition
   fails closed with line evidence.
   Validation plus append runs under one stable lock file. Concurrent writers
   cannot reuse a prior-event hash or interleave bytes.
2. Support append-only events `opened`, `severity_changed`, `closed`,
   `superseded`, and `voided`. Transitions retain the prior description and
   provenance unless a new event explicitly changes them.
3. Validate closure against both a closed issue spec and a matching entry in
   `.prd-os/receipts.jsonl`. Supersession names a live replacement ID. Void
   requires a non-item rationale.
4. Store a reviewed baseline manifest containing the ledger head hash and
   effective pre-existing IDs. Any event appended after that head is new debt,
   including a severity increase or reopen on a baseline ID.
5. Make `gates run` print registered gate failures, new open debt, and
   pre-existing open debt separately. Return nonzero for red registered gates,
   invalid ledger state, or new debt. Pre-existing debt remains visible but
   does not change the exit code by itself.
6. Add views for actionable current work, historical closed or superseded
   scars, and full event history. All derive from the same fold.
7. Before a whole-ledger read above 10,000 events, load a verified checkpoint
   containing the ledger byte offset, head hash, effective fold hashes, and
   schema version, then stream only later events. Any mismatch discards the
   checkpoint and rebuilds it from the authoritative JSONL.

## Alternatives considered

- **Edit stale events in place.** Rejected because it destroys audit history.
- **Keep last-write-wins without validation.** Rejected because malformed or
  invalid transitions can silently change current state.
- **Keep all open debt as one gate failure.** Rejected because the founder
  requires pre-existing debt separated from new debt.

## Scenarios

- **Severity correction.** A prior P0 defect marked minor gets a
  `severity_changed` event. History retains the old severity; current state
  shows the new one.
- **Closure.** A closure event names an issue whose spec says closed and whose
  closeout receipt matches. Missing either proof is rejected.
- **Reopen after baseline.** A baseline item receives a new open event. It is
  reported as new debt, not hidden in the baseline group.
- **Historical queue.** A superseded item appears in scars with its replacement
  link and disappears from actionable open work.

## Resolved decisions

- **File order defines event order.** Rationale: append order is deterministic;
  timestamps are evidence, not ordering authority.
- **History never changes.** Rationale: corrections are events.
- **Closure needs two proofs.** Rationale: frontmatter alone can drift from the
  receipt-based closeout path.
- **Baseline debt is visible but exit-neutral.** Rationale: new work must not
  inherit a permanently red exit from identified old debt.
- **A post-baseline change is new debt.** Rationale: a baseline ID cannot hide a
  reopen or severity increase.

## Risks and rollback

- A schema upgrade can make old events invalid. Versioned readers preserve the
  legacy shape and migration emits new normalization events. Rollback uses the
  prior reader without changing history.
- A bad baseline can hide current work. Baseline generation is reviewed,
  content-hashed, and refuses IDs without valid current events.
- Receipt lookup can reject legitimate historical closures. Those remain open
  until a verified receipt or explicit void event exists.
- Full-history reads grow with the ledger. A derived checkpoint caches a
  verified fold after 10,000 events, but the append-only ledger remains
  authority and can rebuild it on any mismatch.

## Open questions

- Who approves the first pre-existing baseline manifest?
- What exact evidence makes a historical fix eligible for void rather than
  closure against an issue?
- Should the 10,000-event checkpoint threshold become configuration after
  production timing evidence exists?

## AMENDMENT 2026-08-06: the baseline pair is withdrawn (findings 5 and 9)

`scs-baseline-debt-reporting` (finding-5) and `scs-baseline-artifact-proof`
(finding-9) are moved to `status: withdrawn`. Not deferred: building them as
specified would make the standing gate LESS safe than it is today. Evidence
below, all measured 2026-08-06 against `.prd-os/spillover.jsonl`.

**1. The premise moved 17x.** This PRD was written against "73 events, 53 IDs,
33 effective open items". The ledger now holds 860 events, 713 IDs, 570
effective open. Inflow is automated and outflow is manual, so a snapshot-shaped
remedy ages badly by construction.

**2. The exit-neutral bucket the baseline would create already exists, on a
better axis.** `gates run` gained `SPILLOVER_BLOCKING_SEVERITIES` /
`SPILLOVER_NONBLOCKING_SEVERITIES` after this PRD was approved (prd_runner.py).
All 550 `minor` items are ALREADY reported-not-blocking. Baselining them changes
no exit code, prints a second copy of the same list, and adds a manifest to
maintain. Goal 5 ("make `gates run` identify pre-existing debt separately from
new debt") is satisfied on the axis that matters; the remaining gap is not
old-vs-new.

**3. The decisive one: a baseline built today would turn the gate GREEN over
every blocking item it currently holds.** After a same-day recount and two
verified voids, the set is 12 open blocking-severity items: 9 pre-existing
(oldest 2026-06-30, including 2 `blocker`) and 3 created 2026-08-06. A manifest
captures whatever is open when it is written, so all 12 land inside it.

(Correction of record: an earlier draft of this amendment said "all 13
pre-date any manifest writable now". Both halves were wrong — the count was 14
at the time, and 3 of those were created that same day, so "pre-existing" was
11, not 13. The argument survives the recount; the number did not, and a number
handed to the founder has to be the one that survives a recount.)

The spec says pre-existing debt "remains
visible but does not change the exit code by itself", so those 13 become
exit-neutral on the day the baseline lands. That is a bulk hand-clear of exactly
the findings the gate exists to hold, performed by a mechanism whose stated
purpose is auditability. `no-orphan-findings.md` says there are only two ways
out of the ledger, fixed or voided, and "you cannot hand-clear the gate". A
baseline is a third way with a hash on it.

**4. It does not touch the problem the founder actually named.** The complaint
is that 550 items sit at the `minor` DEFAULT, meaning untriaged rather than
assessed. `spillover add` defaults `--severity minor` and records nothing that
distinguishes a defaulted severity from an assessed one, so the two are
indistinguishable after the fact. Exactly 1 of 570 open items has ever carried a
`reclassified_from`. Freezing that population into a reviewed, content-hashed,
exit-neutral manifest does not triage it; it ratifies "nobody looked" as a
signed artifact and makes the untriaged state permanent and blessed.

### What replaces them

**finding-10, `scs-severity-provenance` (new, p1).** Record severity provenance
at write time: `spillover add` stamps `severity_source: "default" | "explicit"`,
and the gate's REPORT line splits "assessed minor" from "never triaged". This is
the precondition for any triage rule at all — a rule cannot key on a field whose
value cannot be distinguished from its default. It is also cheap, it is
append-only, and it makes the 550 a number that can be driven down and watched.

Deliberately NOT included: any bulk reclassification of the existing 550. A
mechanical pass that stamps a severity nobody read is the same hand-clear in a
different coat. The existing population becomes measurable; it does not become
approved.

### The three open questions, answered

- **Who approves the first pre-existing baseline manifest?** Nobody, because the
  artifact is withdrawn. The founder decision hiding underneath it is real and is
  stated plainly in the report accompanying this amendment: making pre-existing
  debt exit-neutral means authorizing 13 specific blocking findings to stop
  blocking. That is an authorize-class call, not an engineering one, and it
  should be taken per-item against named findings rather than as one signature
  over a list of 570 nobody has read.
- **What evidence makes a historical fix eligible for void rather than
  closure?** Unchanged and already coded: `resolve --void <reason>` records a
  non-item with its rationale; `resolve --resolution-ref` requires a provably
  closed issue. No new rule needed, so this question is closed as already
  answered by shipped code.
- **Should the 10,000-event checkpoint threshold become configuration?**
  Premature. The ledger is at 860 events and the whole-file read of the live
  ledger is not a measured cost. `scs-verified-fold-checkpoint` (finding-8) is
  deferred until a timing measurement exists, per its own risk note.

## Evidence

- **E1:** `.prd-os/spillover.jsonl`; deterministic fold command run 2026-07-24:
  73 events, 53 IDs, 33 effective open items.
- **E2:** `plugins/prd-os/scripts/prd_runner.py:951-1049`.
- **E3:** `plugins/prd-os/scripts/prd_runner.py:1055-1114`.
- **E4:** `plugins/prd-os/tests/test_spillover.py:58-123`;
  `plugins/prd-os/tests/test_deferred_spillover.py:70-102`.
- **E5:** `q-system/output/rca/rca-autocapture-session-id-disconnect-2026-06-30.md`;
  `q-system/output/rca/rca-derived-copy-drift-2026-06-30.md`;
  `q-system/output/rca/rca-heartbeat-tail-skip-2026-06-30.md`.

## Issues

```json
[
  {
    "id": "scs-validated-event-fold",
    "finding_id": "finding-1",
    "title": "Implement the validated latest-event fold",
    "priority": "p2",
    "allowed_files": ["plugins/prd-os/scripts/spillover_events.py", "plugins/prd-os/schemas/spillover-event.schema.json", "plugins/prd-os/tests/test_spillover_events.py"],
    "disallowed_files": [".prd-os/spillover.jsonl", "plugins/prd-os/scripts/prd_runner.py", "q-system/**", ".git/**"],
    "required_checks": ["python3 -m pytest -q plugins/prd-os/tests/test_spillover_events.py"],
    "required_reviews": ["prd-os-owner"],
    "acceptance": "Write failing invalid-JSON, invalid-transition, duplicate-ID, and out-of-order-timestamp tests first. Fold valid events by file order and fail closed with line evidence.",
    "bypass_check": "python3 -m pytest -q plugins/prd-os/tests/test_spillover_events.py -k 'invalid or duplicate or timestamp'"
  },
  {
    "id": "scs-lifecycle-events",
    "finding_id": "finding-2",
    "title": "Append closure, supersession, void, and severity events",
    "priority": "p2",
    "allowed_files": ["plugins/prd-os/scripts/prd_runner.py", "plugins/prd-os/tests/test_spillover_lifecycle.py"],
    "disallowed_files": [".prd-os/spillover.jsonl", "plugins/prd-os/schemas/**", "q-system/**", ".git/**"],
    "required_checks": ["python3 -m pytest -q plugins/prd-os/tests/test_spillover_lifecycle.py"],
    "required_reviews": ["prd-os-owner"],
    "acceptance": "Write failing stale-status, severity-change, invalid-supersession, and history-mutation tests first. Express every correction as a new event.",
    "bypass_check": "python3 -m pytest -q plugins/prd-os/tests/test_spillover_lifecycle.py -k 'stale or severity or mutate'"
  },
  {
    "id": "scs-closure-receipts",
    "finding_id": "finding-3",
    "title": "Require issue and closeout receipts for closure",
    "priority": "p2",
    "allowed_files": ["plugins/prd-os/scripts/spillover_receipts.py", "plugins/prd-os/tests/test_spillover_receipts.py"],
    "disallowed_files": [".prd-os/spillover.jsonl", ".prd-os/receipts.jsonl", "plugins/prd-os/scripts/prd_runner.py", "q-system/**"],
    "required_checks": ["python3 -m pytest -q plugins/prd-os/tests/test_spillover_receipts.py"],
    "required_reviews": ["prd-os-owner"],
    "acceptance": "Write failing closed-frontmatter-without-receipt, mismatched-PRD, unknown-issue, and forged-receipt tests first. Require both closed issue state and a matching closeout record.",
    "bypass_check": "python3 -m pytest -q plugins/prd-os/tests/test_spillover_receipts.py -k 'missing or mismatch or forged'"
  },
  {
    "id": "scs-actionable-and-scar-views",
    "finding_id": "finding-4",
    "title": "Separate actionable current work from historical scars",
    "priority": "p2",
    "allowed_files": ["plugins/prd-os/scripts/spillover_views.py", "plugins/prd-os/tests/test_spillover_views.py"],
    "disallowed_files": [".prd-os/spillover.jsonl", "plugins/prd-os/scripts/prd_runner.py", "q-system/**", ".git/**"],
    "required_checks": ["python3 -m pytest -q plugins/prd-os/tests/test_spillover_views.py"],
    "required_reviews": ["prd-os-owner"],
    "acceptance": "Write failing closed-in-open, superseded-without-link, and history-loss tests first. Derive actionable, scars, and full-history views from one fold.",
    "bypass_check": "python3 -m pytest -q plugins/prd-os/tests/test_spillover_views.py -k 'closed_in_open or missing_link or history'"
  },
  {
    "id": "scs-baseline-debt-reporting",
    "finding_id": "finding-5",
    "title": "Separate pre-existing and new debt in gates run",
    "priority": "p2",
    "allowed_files": ["plugins/prd-os/scripts/prd_runner.py", "plugins/prd-os/schemas/spillover-baseline.schema.json", "plugins/prd-os/tests/test_spillover_baseline.py", ".prd-os/spillover-baseline.json"],
    "disallowed_files": [".prd-os/spillover.jsonl", ".prd-os/gates.jsonl", "q-system/**", ".git/**"],
    "required_checks": ["python3 -m pytest -q plugins/prd-os/tests/test_spillover_baseline.py"],
    "required_reviews": ["prd-os-owner"],
    "acceptance": "Write failing baseline-reopen, severity-increase, new-ID, and invalid-head-hash tests first. Print old and new debt separately and return nonzero only for new debt, invalid ledger state, or red registered gates.",
    "bypass_check": "python3 -m pytest -q plugins/prd-os/tests/test_spillover_baseline.py -k 'reopen or severity or invalid_head'"
  },
  {
    "id": "scs-spillover-regression-matrix",
    "finding_id": "finding-6",
    "title": "Lock duplicate, stale, reference, and severity regressions",
    "priority": "p2",
    "allowed_files": ["plugins/prd-os/tests/test_spillover_regressions.py"],
    "disallowed_files": [".prd-os/spillover.jsonl", "plugins/prd-os/scripts/**", "q-system/**", ".git/**"],
    "required_checks": ["python3 -m pytest -q plugins/prd-os/tests/test_spillover_regressions.py"],
    "required_reviews": ["prd-os-owner"],
    "acceptance": "Write the failing regression fixtures first. Cover duplicate IDs, stale status, invalid resolution references, severity changes, and all three RCA event shapes.",
    "bypass_check": "python3 -m pytest -q plugins/prd-os/tests/test_spillover_regressions.py -k 'duplicate or stale or invalid_reference or severity'"
  },
  {
    "id": "scs-concurrent-append-lock",
    "finding_id": "finding-7",
    "title": "Make spillover validation and append atomic",
    "priority": "p2",
    "allowed_files": ["plugins/prd-os/scripts/spillover_lock.py", "plugins/prd-os/tests/test_spillover_concurrency.py"],
    "disallowed_files": [".prd-os/spillover.jsonl", "plugins/prd-os/scripts/prd_runner.py", "q-system/**", ".git/**"],
    "required_checks": ["python3 -m pytest -q plugins/prd-os/tests/test_spillover_concurrency.py"],
    "required_reviews": ["prd-os-owner"],
    "acceptance": "Write a failing N-process append reproducer first. Hold one stable lock across prior-event validation and append, preserve line integrity, and reject stale prior hashes.",
    "bypass_check": "python3 -m pytest -q plugins/prd-os/tests/test_spillover_concurrency.py -k n_process"
  },
  {
    "id": "scs-verified-fold-checkpoint",
    "finding_id": "finding-8",
    "title": "Bound spillover reads with a verified fold checkpoint",
    "priority": "p2",
    "allowed_files": ["plugins/prd-os/schemas/spillover-checkpoint.schema.json", "plugins/prd-os/scripts/spillover_checkpoint.py", "plugins/prd-os/tests/test_spillover_checkpoint.py"],
    "disallowed_files": [".prd-os/spillover.jsonl", "plugins/prd-os/scripts/prd_runner.py", "q-system/**", ".git/**"],
    "required_checks": ["python3 -m pytest -q plugins/prd-os/tests/test_spillover_checkpoint.py"],
    "required_reviews": ["prd-os-owner"],
    "acceptance": "Write failing 10,001-event boot, stale-offset, and bad-head-hash tests first. Checkpoint before whole-file consumption and rebuild from JSONL on mismatch.",
    "bypass_check": "python3 -m pytest -q plugins/prd-os/tests/test_spillover_checkpoint.py -k 'boot_bound or stale or bad_hash'"
  },
  {
    "id": "scs-baseline-artifact-proof",
    "finding_id": "finding-9",
    "title": "Create the reviewed baseline artifact with event hashes",
    "priority": "p2",
    "allowed_files": [".prd-os/spillover-baseline.json", "plugins/prd-os/tests/test_spillover_baseline_artifact.py"],
    "disallowed_files": [".prd-os/spillover.jsonl", ".prd-os/gates.jsonl", "plugins/prd-os/scripts/**", "q-system/**"],
    "required_checks": ["python3 -m pytest -q plugins/prd-os/tests/test_spillover_baseline_artifact.py"],
    "required_reviews": ["prd-os-owner"],
    "acceptance": "Write failing missing-head and changed-effective-event tests first. Record reviewed IDs, ledger head hash, and effective event hashes so later changes are classified as new debt.",
    "bypass_check": "python3 -m pytest -q plugins/prd-os/tests/test_spillover_baseline_artifact.py -k changed_event"
  }
]
```
