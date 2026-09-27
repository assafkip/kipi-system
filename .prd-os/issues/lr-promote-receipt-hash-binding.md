---
id: lr-promote-receipt-hash-binding
title: A promotion receipt binds path, git blob hash, source instance and decider; the lessons guard passes a divergent lesson only on a matching done receipt
status: closed
priority: p1
parent_prd: prd-lessons-rail-and-up-rail-2026-09-02
allowed_files:
  - kipi-promote.sh
  - kipi-push-upstream.sh
  - q-system/.q-system/scripts/lessons_scrub.py
  - q-system/.q-system/tests/test_promotion_receipt.py
disallowed_files:
  - .claude/**
  - plugins/prd-os/**
  - .prd-os/**
  - q-consult/**
  - kipi-update.sh
required_checks:
  - python3 -m pytest -q q-system/.q-system/tests/test_promotion_receipt.py
required_reviews: []
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/test_promotion_receipt.py -k 'stale_receipt_refused or no_receipt_refused'"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-lessons-rail-and-up-rail-2026-09-02 finding=finding-1 at=2026-09-02T00:25:35Z -->

# A promotion receipt binds path, git blob hash, source instance and decider; the lessons guard passes a divergent lesson only on a matching done receipt

## Context

Parent PRD: `.prd-os/prds/prd-lessons-rail-and-up-rail-2026-09-02.md`

## Acceptance

RED first against two tmp git repos (instance and skeleton, the skeleton reachable as FETCH_HEAD): a receipt row is {path, blob, from_instance, decided_by, scrub, status, at} where blob is git hash-object of the promoted content; the guard passes a divergent lesson whose instance blob equals a done receipt's blob for that path, refuses one whose content changed after the receipt (stale receipt), refuses one with no receipt, and is unchanged for deletions and for uncommitted lessons; decided_by defaults to the invoking user and can be set with --decided-by.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] A promotion receipt binds path, git blob hash, source instance and decider; the lessons guard passes a divergent lesson only on a matching done receipt

## Amendments

### 2026-09-02T02:22:24Z
Reason: Claude standard review blocker: the receipt recorded from_instance as the absolute path, which carries /Users/ and the owner's name into a file that fans out to every instance and trips the push tripwire. The fix records the registry instance NAME; the lookup (instance_name_for) belongs in lessons_scrub.py next to clients_file_for_instance, so that module joins allowed_files.

Before:
- allowed_files: ['kipi-promote.sh', 'kipi-push-upstream.sh', 'q-system/.q-system/tests/test_promotion_receipt.py']
- required_checks: ['python3 -m pytest -q q-system/.q-system/tests/test_promotion_receipt.py']
- disallowed_files: ['.claude/**', 'plugins/prd-os/**', '.prd-os/**', 'q-consult/**', 'kipi-update.sh']

After:
- allowed_files: ['kipi-promote.sh', 'kipi-push-upstream.sh', 'q-system/.q-system/tests/test_promotion_receipt.py']
- required_checks: ['python3 -m pytest -q q-system/.q-system/tests/test_promotion_receipt.py']
- disallowed_files: ['.claude/**', 'plugins/prd-os/**', '.prd-os/**', 'q-consult/**', 'kipi-update.sh']
