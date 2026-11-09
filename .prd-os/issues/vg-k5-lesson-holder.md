---
id: vg-k5-lesson-holder
title: Lessons carry a linked held_by or a dated prose_accepted, from every writer
status: open
priority: p1
parent_prd: prd-voicegate-skeleton-2026-11-09
allowed_files:
  - q-system/.q-system/scripts/lessons-validator.py
  - q-system/.q-system/scripts/lessons-distill.py
  - q-system/.q-system/scripts/lessons-daily.sh
  - q-system/.q-system/scripts/lesson-note.sh
  - q-system/lessons/README.md
  - q-system/.q-system/scripts/test/test_lessons_validator_holder.py
  - q-system/.q-system/capability/expected_tests/q-system__.q-system__scripts__test__test_lessons_validator_holder.py.json
disallowed_files: []
required_checks:
  - python3 -m pytest -q q-system/.q-system/scripts/test/test_lessons_validator_holder.py
required_reviews: []
bypass_check: "python3 -m pytest -q q-system/.q-system/scripts/test/test_lessons_validator_holder.py"
gate_lifecycle: historical-receipt
deliverables_count: 5
---
<!-- generated-by: prd_split.py prd=prd-voicegate-skeleton-2026-11-09 finding=finding-12 at=2026-11-09T18:24:23Z -->

# Lessons carry a linked held_by or a dated prose_accepted, from every writer

## Context

Parent PRD: `.prd-os/prds/prd-voicegate-skeleton-2026-11-09.md`

## Acceptance

held_by: a repo-relative path that exists, is a hook, script or test file, and contains the lesson id (the same linkage rule_gate.py enforces for RULE-2026-11-08-CODE). prose_accepted: a reason and a YYYY-MM-DD date. Required on new and changed lessons; lessons already on origin/main without either are counted as debt and printed, not refused.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Red first: a new lesson with neither field is refused
- [ ] held_by naming a missing file is refused; held_by naming a file that lacks the lesson id is refused; held_by as an absolute path is refused
- [ ] The token denylist runs over every new field value, not only the title
- [ ] lessons-distill.py, lessons-daily.sh and lesson-note.sh each emit a valid field (an auto-distilled lesson gets prose_accepted with its reason and date) or run the validator; a test drives each writer on a fixture
- [ ] Existing lessons without either field are counted as debt by a printed number
