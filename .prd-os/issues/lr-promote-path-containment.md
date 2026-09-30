---
id: lr-promote-path-containment
title: kipi promote exists, is registered in the CLI, and refuses any path that is not a regular file on a symlink-free real path inside q-system/
status: closed
priority: p1
parent_prd: prd-lessons-rail-and-up-rail-2026-09-02
allowed_files:
  - kipi-promote.sh
  - kipi
  - q-system/.q-system/tests/test_promotion_receipt.py
  - q-system/.q-system/capability/expected_tests/q-system__.q-system__tests__test_promotion_receipt.py.json
disallowed_files:
  - .claude/**
  - plugins/prd-os/**
  - .prd-os/**
  - q-consult/**
  - kipi-update.sh
required_checks:
  - python3 -m pytest -q q-system/.q-system/tests/test_promotion_receipt.py
required_reviews: []
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/test_promotion_receipt.py -k containment"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-lessons-rail-and-up-rail-2026-09-02 finding=finding-2 at=2026-09-02T00:25:35Z -->

# kipi promote exists, is registered in the CLI, and refuses any path that is not a regular file on a symlink-free real path inside q-system/

## Context

Parent PRD: `.prd-os/prds/prd-lessons-rail-and-up-rail-2026-09-02.md`

## Acceptance

RED first against tmp copies of an instance and a skeleton (never the live trees; KIPI_PROMOTE_SKELETON and KIPI_PROMOTE_INSTANCE point at them): an absolute input, a path with '..', a symlink (the file or any parent), a directory, a device or fifo, and a path outside q-system/ (including one under the instance_q_dir) each exit 2 with no copy and no receipt; a plain relative q-system/ path copies to the same relative path in the skeleton, creating parents; the CLI registers `kipi promote` and `kipi help` names it. The scrub and the receipt are the next two slices; this slice copies only when KIPI_PROMOTE_UNSCRUBBED=1 under pytest, and refuses otherwise, so the containment slice can never ship as a working promoter without the scrub.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] kipi promote exists, is registered in the CLI, and refuses any path that is not a regular file on a symlink-free real path inside q-system/
