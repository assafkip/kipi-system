---
id: rf-converge-untracked-recovery
title: converge recovers an UNTRACKED (and ignored) fragment, not only a modified line
status: open
priority: p1
parent_prd: prd-receipts-fragments-2026-10-01
allowed_files:
  - q-system/.q-system/scripts/converge.sh
  - q-system/.q-system/scripts/test/test-converge*.sh
  - q-system/.q-system/scripts/test/fixtures/silent-success/GREEN-checked-swallow.converge.sh
  - q-system/.q-system/scripts/test/test-rf-converge-untracked-recovery.sh
disallowed_files: []
required_checks:
  - bash q-system/.q-system/scripts/test/test-rf-converge-untracked-recovery.sh
required_reviews: []
bypass_check: "bash q-system/.q-system/scripts/test/test-rf-converge-untracked-recovery.sh"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-receipts-fragments-2026-10-01 finding=finding-1 at=2026-10-01T20:47:01Z -->

# converge recovers an UNTRACKED (and ignored) fragment, not only a modified line

## Context

Parent PRD: `.prd-os/prds/prd-receipts-fragments-2026-10-01.md`

## Acceptance

A run killed after writing a fragment and before committing it is finished by the next run (committed and pushed), never dedup'd into a permanent miss.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] converge recovers an UNTRACKED (and ignored) fragment, not only a modified line
