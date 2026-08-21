---
id: lessons-payload-ceiling
title: Uncap lesson titles and give the SessionStart payload a measured ceiling with a failing test
status: open
priority: p1
parent_prd: prd-enforced-claim-verification-2026-08-21
allowed_files:
  - q-system/hooks/lessons-index.py
  - q-system/.q-system/scripts/test_lessons_index.py
disallowed_files: []
required_checks:
  - python3 -m pytest q-system/.q-system/scripts/test_lessons_index.py -q
required_reviews: []
bypass_check: "no unconditional slice of the item list remains and a ceiling constant is asserted by the test"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-enforced-claim-verification-2026-08-21 finding=finding-12 at=2026-08-21T17:23:12Z -->

# Uncap lesson titles and give the SessionStart payload a measured ceiling with a failing test

## Context

Parent PRD: `.prd-os/prds/prd-enforced-claim-verification-2026-08-21.md`

## Acceptance

<!-- fill in -->

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Uncap lesson titles and give the SessionStart payload a measured ceiling with a failing test
