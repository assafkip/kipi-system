---
id: prd-fail-closed-fleet-updater-2026-07-24
title: Fail-Closed Fleet Updater
status: approved
created_at: 2026-07-24T20:56:00Z
updated_at: 2026-07-24T20:57:36Z
owner: senior-staff
reviewers: []
findings_path: .prd-os/findings/prd-fail-closed-fleet-updater-2026-07-24-findings.jsonl
codex_reviewed_at: 2026-07-24T20:57:03Z
---

# Fail-Closed Fleet Updater

## Problem

`kipi-update.sh` snapshots instance-owned files, then executes
`rsync --delete` [`kipi-update.sh:138-188`]. Preservation commands can tolerate
failure, and updater commits use `--no-verify` with failure suppression
[`kipi-update.sh:95-99`, `kipi-update.sh:196`, `kipi-update.sh:287`]. The dry
run shows an rsync item preview but does not model settings merge, plugin sync,
restore, or the final commit diff [`kipi-update.sh:209-287`].

Existing tests prove one untracked file and one symlink survive, but do not
cover tracked instance automation, helper failure, registry layout variants,
or final-state equivalence
[`q-system/.q-system/scripts/test/test-kipi-update-safety.sh:28-41`].
The fleet record says two instance scanners died after an update and records a
preservation guard as the response
[`q-system/canonical/autonomous-systems-record-2026-06-30.md:24-29`,
`q-system/canonical/autonomous-systems-record-2026-06-30.md:71-99`].
Open spillover also records tracked-script deletion, incomplete dry-run
coverage, WIP auto-commits, and null or nonstandard registry fields
[`.prd-os/spillover.jsonl:19`, `.prd-os/spillover.jsonl:27-28`,
`.prd-os/spillover.jsonl:51`, `.prd-os/spillover.jsonl:70`].

## Goals

- Reproduce snapshot or preservation-helper failure before destructive rsync.
- Stop before rsync unless snapshot completeness and restoreability are proven.
- Make dry run model preservation, restore, settings merge, agent and rule
  sync, plugin sync, and the exact final commit diff.
- Preserve tracked and untracked instance-owned canonical, `my-project`,
  memory, output, bus, automation, and registry-derived state.
- Make updater-created commits pass the relevant hooks with no silent
  `--no-verify` path.
- Prove rollback and cover nonstandard `subtree_prefix` and `instance_q_dir`
  fixtures.
- Close the updater defect shapes represented by the cited RCAs and spillover,
  without editing spillover history.

## Non-goals

- Updating any external instance repo during this PRD program.
- Changing product content, canonical schemas, or instance registry entries.
- Replacing Git or rsync.
- Making updater commits when a worktree cannot be preserved without mixing
  unrelated user changes.

## Proposed approach

1. Add a deterministic helper-failure fixture. Intercept snapshot or manifest
   creation, prove the old updater reaches the destructive boundary, then make
   the boundary require a verified preservation receipt.
2. Build a source, preservation, and restore manifest from a committed ownership
   contract plus the registry-derived instance layout. The contract classifies
   preserved state roots, instance automation outside the managed skeleton,
   and generic managed destinations. Enumerate every managed destination before
   rsync, hash tracked and untracked owned paths, and refuse unknown layout
   values, unclassified paths, or incomplete snapshots.
3. Construct dry run in a temporary fixture copy. Apply every planned phase,
   produce the final filesystem and Git diff, and discard the fixture. The
   manifest is identical between dry and real modes.
4. Create updater commits through the configured hook path. A failing hook
   aborts the commit and reports the unchanged or recoverable state.
5. Prove rollback from the receipt after failures before sync, during restore,
   after settings merge, and after commit creation.
6. Use one versioned receipt schema for updater, preservation helper, dry run,
   and rollback. The producer and every consumer reject unknown schema versions.

## Alternatives considered

- **Keep rsync preview as dry run.** Rejected because it omits later phases and
  cannot predict the final commit. [`kipi-update.sh:209-287`]
- **Add more rsync exclusions.** Rejected because registry layouts vary and
  instance-owned tracked files already escaped static assumptions. [E4]
- **Keep `--no-verify` for automation.** Rejected because it bypasses the
  repository's executable enforcement.

## Scenarios

- **Snapshot helper fails.** The updater has not called rsync, returns nonzero,
  leaves the instance unchanged, and points to the failed proof.
- **Dirty instance.** Tracked and untracked owned files are represented in the
  manifest. Unrelated WIP is not folded into an updater commit.
- **Nonstandard layout.** Fixtures with null `subtree_prefix`, explicit
  `instance_q_dir`, and standalone type either resolve safely or fail before
  mutation.
- **Dry run.** The reported final diff matches a real run against the same
  disposable fixture byte for byte.
- **Hook failure.** The updater commit is refused without `--no-verify`, and
  rollback restores the pre-run state.

## Resolved decisions

- **Preservation proof is a hard precondition.** Rationale: a helper used before
  `rsync --delete` must fail closed.
- **Dry run models final state.** Rationale: an rsync delta is not the updater's
  final effect.
- **Registry fields drive layout.** Rationale: spillover proves static defaults
  fail for null and custom values. [E4]
- **Hooks apply to updater commits.** Rationale: automation is not a bypass
  class.
- **Updater edits are serialized.** Rationale: `fcu-preservation-precondition`
  lands first, `fcu-dry-run-final-state` rebases on it, and
  `fcu-hook-safe-commits` lands last. Each reruns the preceding issue checks.
- **Ownership is executable data.** Rationale: registry locations alone do not
  say which paths are instance-owned, so the updater must validate a committed,
  self-enumerating ownership contract before mutation.
- **Receipts have one schema.** Rationale: rollback cannot prove recovery if it
  interprets paths, hashes, or phases differently from the updater.

## Risks and rollback

- A false preservation failure can pause fleet updates. The receipt names the
  exact missing path or hash so an operator can correct the fixture or data.
- A bad final-state model can create false confidence. The equivalence test runs
  dry and real modes against the same disposable fixture.
- Hook behavior can strand a prepared commit. The updater leaves the worktree
  recoverable and emits the rollback command and receipt. It does not suppress
  the hook.
- Rollback can overwrite post-update work. It applies only to receipt-listed
  updater changes and refuses if hashes show later edits.

## Open questions

- Which existing hook set is the authoritative updater commit contract before
  `enforcement-instruction-contract` lands?
- Should a standalone registry entry be skipped or use a separately declared
  update adapter?
- What retention period applies to successful preservation receipts and
  snapshots?

## Evidence

- **E1:** `kipi-update.sh:95-99`, `kipi-update.sh:138-196`,
  `kipi-update.sh:209-287`.
- **E2:** `q-system/.q-system/scripts/test/test-kipi-update-safety.sh:28-41`;
  `q-system/.q-system/scripts/test/test-kipi-rollback.sh:19-108`.
- **E3:** `q-system/canonical/autonomous-systems-record-2026-06-30.md:24-29`,
  `q-system/canonical/autonomous-systems-record-2026-06-30.md:71-99`.
- **E4:** `.prd-os/spillover.jsonl:19`, `.prd-os/spillover.jsonl:27-28`,
  `.prd-os/spillover.jsonl:51`, `.prd-os/spillover.jsonl:54`,
  `.prd-os/spillover.jsonl:70`.

## Issues

```json
[
  {
    "id": "fcu-preservation-precondition",
    "finding_id": "finding-1",
    "title": "Fail closed before rsync when preservation proof fails",
    "priority": "p0",
    "allowed_files": ["kipi-update.sh", "kipi-update-preserve-scan.py", "test-kipi-update-preserve-scan.sh", "q-system/.q-system/scripts/test/test-kipi-update-preservation-failure.sh", "q-system/.q-system/scripts/test/test-kipi-update-safety.sh"],
    "disallowed_files": ["instance-registry.json", "q-system/canonical/**", ".prd-os/**", ".git/**"],
    "required_checks": ["bash q-system/.q-system/scripts/test/test-kipi-update-preservation-failure.sh", "bash q-system/.q-system/scripts/test/test-kipi-update-safety.sh", "bash test-kipi-update-preserve-scan.sh"],
    "required_reviews": ["updater-owner"],
    "acceptance": "Write the failing helper-failure reproducer first. Prove rsync is never invoked without a complete snapshot and verified preservation receipt.",
    "bypass_check": "bash q-system/.q-system/scripts/test/test-kipi-update-preservation-failure.sh --assert-no-rsync"
  },
  {
    "id": "fcu-dry-run-final-state",
    "finding_id": "finding-2",
    "title": "Make dry run predict the exact final updater state",
    "priority": "p0",
    "allowed_files": ["kipi-update.sh", "q-system/.q-system/scripts/test/test-kipi-update-dry-final-state.sh"],
    "disallowed_files": ["instance-registry.json", "q-system/canonical/**", ".prd-os/**", ".git/**"],
    "required_checks": ["bash q-system/.q-system/scripts/test/test-kipi-update-dry-final-state.sh"],
    "required_reviews": ["updater-owner"],
    "acceptance": "Write the failing dry-versus-real equivalence test first. Model restore, settings merge, agents, rules, plugins, and final commit diff in a disposable fixture.",
    "bypass_check": "bash q-system/.q-system/scripts/test/test-kipi-update-dry-final-state.sh --assert-byte-equivalent"
  },
  {
    "id": "fcu-owned-state-manifest",
    "finding_id": "finding-3",
    "title": "Preserve tracked and untracked registry-derived owned state",
    "priority": "p0",
    "allowed_files": ["q-system/.q-system/scripts/update-preservation-manifest.py", "q-system/.q-system/scripts/test/test-update-preservation-manifest.py"],
    "disallowed_files": ["kipi-update.sh", "instance-registry.json", "q-system/canonical/**", ".prd-os/**"],
    "required_checks": ["python3 q-system/.q-system/scripts/test/test-update-preservation-manifest.py"],
    "required_reviews": ["updater-owner"],
    "acceptance": "Write failing tracked, untracked, null-prefix, custom-q-dir, and standalone fixtures first. Cover canonical, project, memory, output, bus, and instance automation.",
    "bypass_check": "python3 q-system/.q-system/scripts/test/test-update-preservation-manifest.py --negative-layouts"
  },
  {
    "id": "fcu-hook-safe-commits",
    "finding_id": "finding-4",
    "title": "Make updater commits pass active hooks without bypass",
    "priority": "p0",
    "allowed_files": ["kipi-update.sh", "q-system/.q-system/scripts/test/test-kipi-update-hook-contract.sh"],
    "disallowed_files": [".githooks/**", "lefthook.yml", "instance-registry.json", ".prd-os/**"],
    "required_checks": ["bash q-system/.q-system/scripts/test/test-kipi-update-hook-contract.sh"],
    "required_reviews": ["enforcement-owner"],
    "acceptance": "Write the failing no-verify reproducer first. Remove silent hook bypasses, abort on hook failure, and leave unrelated WIP outside updater commits.",
    "bypass_check": "bash q-system/.q-system/scripts/test/test-kipi-update-hook-contract.sh --reject-no-verify"
  },
  {
    "id": "fcu-rollback-matrix",
    "finding_id": "finding-5",
    "title": "Prove rollback across updater failure phases",
    "priority": "p0",
    "allowed_files": ["kipi-rollback.sh", "q-system/.q-system/scripts/test/test-kipi-rollback-matrix.sh"],
    "disallowed_files": ["kipi-update.sh", "instance-registry.json", "q-system/canonical/**", ".prd-os/**"],
    "required_checks": ["bash q-system/.q-system/scripts/test/test-kipi-rollback-matrix.sh"],
    "required_reviews": ["updater-owner"],
    "acceptance": "Write failing phase-injection tests first. Restore only receipt-listed updater changes and refuse rollback over later user edits.",
    "bypass_check": "bash q-system/.q-system/scripts/test/test-kipi-rollback-matrix.sh --assert-later-edit-refusal"
  },
  {
    "id": "fcu-ownership-contract",
    "finding_id": "finding-6",
    "title": "Define and enumerate instance-owned paths before mutation",
    "priority": "p0",
    "allowed_files": ["q-system/.q-system/config/instance-ownership-contract.json", "q-system/.q-system/scripts/test/test-instance-ownership-contract.py"],
    "disallowed_files": ["kipi-update.sh", "instance-registry.json", "q-system/canonical/**", ".prd-os/**"],
    "required_checks": ["python3 q-system/.q-system/scripts/test/test-instance-ownership-contract.py"],
    "required_reviews": ["updater-owner"],
    "acceptance": "Write failing unclassified-path and new-destination tests first. Enumerate every managed destination and classify preserved state, instance automation, and generic managed paths from the contract plus registry.",
    "bypass_check": "python3 q-system/.q-system/scripts/test/test-instance-ownership-contract.py --unclassified-must-fail"
  },
  {
    "id": "fcu-serialized-orchestration",
    "finding_id": "finding-7",
    "title": "Enforce updater implementation order for shared orchestration",
    "priority": "p0",
    "allowed_files": ["q-system/.q-system/scripts/test/test-updater-issue-sequence.py"],
    "disallowed_files": ["kipi-update.sh", "instance-registry.json", "q-system/canonical/**", ".prd-os/**"],
    "required_checks": ["python3 q-system/.q-system/scripts/test/test-updater-issue-sequence.py"],
    "required_reviews": ["updater-owner"],
    "acceptance": "Write the failing out-of-order test first. Require preservation precondition, then final-state dry run, then hook-safe commits, with all prior checks rerun at each step.",
    "bypass_check": "python3 q-system/.q-system/scripts/test/test-updater-issue-sequence.py --reject-out-of-order"
  },
  {
    "id": "fcu-shared-receipt-schema",
    "finding_id": "finding-8",
    "title": "Create one versioned updater and rollback receipt schema",
    "priority": "p0",
    "allowed_files": ["q-system/.q-system/schemas/updater-receipt.schema.json", "q-system/.q-system/scripts/test/test-updater-receipt-contract.py"],
    "disallowed_files": ["kipi-update.sh", "kipi-rollback.sh", "instance-registry.json", ".prd-os/**"],
    "required_checks": ["python3 q-system/.q-system/scripts/test/test-updater-receipt-contract.py"],
    "required_reviews": ["updater-owner"],
    "acceptance": "Write failing producer-consumer compatibility tests first. Lock path, hash, phase, mode, schema-version, and rollback fields and reject unknown versions.",
    "bypass_check": "python3 q-system/.q-system/scripts/test/test-updater-receipt-contract.py --producer-consumer-mismatch"
  }
]
```
