---
id: lessons-payload-ceiling
title: Uncap lesson titles and give the SessionStart payload a measured ceiling with a failing test
status: closed
priority: p1
parent_prd: prd-enforced-claim-verification-2026-08-21
allowed_files:
  - q-system/hooks/lessons-index.py
  - q-system/.q-system/scripts/test_lessons_index.py
  - q-system/hooks/test/test-lessons-index.sh
  - q-system/.q-system/capability-manifest.json
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
- [x] Uncap lesson titles and give the SessionStart payload a measured ceiling with a failing test

## Amendments

### 2026-08-21T18:30:47Z
Reason: Two files this change BROKE or SHOULD HAVE TOUCHED and my manifest did not list. (1) q-system/hooks/test/test-lessons-index.sh asserts 25 lessons yield exactly 20 titles; removing the cap makes it fail, verified RC=1. Shipping a green PRD on top of a red pre-existing test is the false-green this whole PRD is about. (2) capability-manifest.json declares the tests the capability gate runs; none of this PRD's three new test files were declared, so they were present-but-undeclared - written, passing locally, and gated by nothing.

Before:
- allowed_files: ['q-system/hooks/lessons-index.py', 'q-system/.q-system/scripts/test_lessons_index.py']
- required_checks: ['python3 -m pytest q-system/.q-system/scripts/test_lessons_index.py -q']
- disallowed_files: []

After:
- allowed_files: ['q-system/hooks/lessons-index.py', 'q-system/.q-system/scripts/test_lessons_index.py', 'q-system/hooks/test/test-lessons-index.sh', 'q-system/.q-system/capability-manifest.json']
- required_checks: ['python3 -m pytest q-system/.q-system/scripts/test_lessons_index.py -q']
- disallowed_files: []
