---
id: vg-k2-worker-header
title: linear-worker.sh header names the merge it runs
status: open
priority: p2
parent_prd: prd-voicegate-skeleton-2026-11-09
allowed_files:
  - q-system/.q-system/scripts/linear-worker.sh
  - q-system/.q-system/scripts/test/test-linear-worker-header.sh
  - q-system/.q-system/capability/expected_tests/q-system__.q-system__scripts__test__test-linear-worker-header.sh.json
disallowed_files: []
required_checks:
  - bash q-system/.q-system/scripts/test/test-linear-worker-header.sh
required_reviews: []
bypass_exempt: "Comment edit in the worker header; no gate or data path to bypass. The test pins the comment against the code."
deliverables_count: 2
---
<!-- generated-by: prd_split.py prd=prd-voicegate-skeleton-2026-11-09 finding=finding-20 at=2026-11-09T18:24:23Z -->

# linear-worker.sh header names the merge it runs

## Context

Parent PRD: `.prd-os/prds/prd-voicegate-skeleton-2026-11-09.md`

## Acceptance

Header comment only; no behaviour change in linear-worker.sh.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Red first: a test that the header merge sentence names a function defined in the file and does not say merging is the founder's (red on today's line 12)
- [ ] Line 12 names arm_automerge, the reviewer verdict it waits for, and that merging is Sana's
