---
id: lr-lessons-label-collision
title: The fanned-out lessons-daily installer refuses outside the skeleton; the skeleton gets its plist template and a label-uniqueness test
status: open
priority: p1
parent_prd: prd-lessons-rail-and-up-rail-2026-09-02
allowed_files:
  - q-system/.q-system/scripts/install-lessons-daily.sh
  - q-system/.q-system/scripts/com.kipi.lessons-daily.plist
  - q-system/.q-system/tests/test_lessons_daily_label.py
  - q-system/.q-system/capability/expected_tests/q-system__.q-system__tests__test_lessons_daily_label.py.json
disallowed_files:
  - .claude/**
  - plugins/prd-os/**
  - .prd-os/**
  - q-consult/**
required_checks:
  - python3 -m pytest -q q-system/.q-system/tests/test_lessons_daily_label.py
required_reviews: []
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/test_lessons_daily_label.py -k 'unique or refuses'"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-lessons-rail-and-up-rail-2026-09-02 finding=finding-5 at=2026-09-02T00:25:35Z -->

# The fanned-out lessons-daily installer refuses outside the skeleton; the skeleton gets its plist template and a label-uniqueness test

## Context

Parent PRD: `.prd-os/prds/prd-lessons-rail-and-up-rail-2026-09-02.md`

## Acceptance

RED first: install-lessons-daily.sh resolves its repo root, reads instance-registry.json there (or under the subtree prefix), and exits 2 without writing a plist unless the root equals the registry's skeleton path; run in a tmp tree with a fixture registry naming another skeleton and a tmp HOME, it refuses and HOME/Library/LaunchAgents stays empty; run in a tmp tree whose fixture registry names that tree as skeleton, it writes the plist under the tmp HOME. A com.kipi.lessons-daily.plist template exists with __KIPI_REPO__/__HOME__/__USER__, Weekday 1 06:00, no /Users/ literal. A test derives every Label from every com.kipi.*.plist template and every install-*.sh in the skeleton and asserts each label is claimed exactly once.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] The fanned-out lessons-daily installer refuses outside the skeleton; the skeleton gets its plist template and a label-uniqueness test
