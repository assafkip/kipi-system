---
id: rf-fragment-dir-from-config
title: The fragment directory is derived from config receipts_path in one place, so an override moves writers and readers together
status: open
priority: p1
parent_prd: prd-receipts-fragments-2026-10-01
allowed_files:
  - plugins/prd-os/scripts/config.py
  - plugins/prd-os/scripts/receipts_store.py
  - plugins/kipi-dsse/scripts/issue_runner.py
  - plugins/kipi-dsse/scripts/receipts_store.py
  - q-system/.q-system/scripts/receipts_store.py
  - plugins/prd-os/tests/test_receipts_store.py
disallowed_files: []
required_checks:
  - python3 -m pytest plugins/prd-os/tests/test_receipts_store.py -q
required_reviews: []
bypass_check: "python3 -m pytest plugins/prd-os/tests/test_receipts_store.py -q"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-receipts-fragments-2026-10-01 finding=finding-8 at=2026-10-01T20:47:01Z -->

# The fragment directory is derived from config receipts_path in one place, so an override moves writers and readers together

## Context

Parent PRD: `.prd-os/prds/prd-receipts-fragments-2026-10-01.md`

## Acceptance

With receipts_path overridden, the writer and every reader use the same derived directory.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] The fragment directory is derived from config receipts_path in one place, so an override moves writers and readers together
