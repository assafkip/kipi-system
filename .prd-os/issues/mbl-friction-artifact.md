---
id: mbl-friction-artifact
title: Friction artifact with ids and redaction, weekly pass via slack_founder, empty distinct from broken
status: open
priority: p1
parent_prd: prd-morning-brief-learns-2026-09-01
allowed_files:
  - q-system/.q-system/scripts/friction-note.sh
  - q-system/.q-system/scripts/weekly-improve.py
  - q-system/.q-system/tests/test_weekly_improve.py
  - q-system/.q-system/capability/expected_tests/q-system__.q-system__tests__test_weekly_improve.py.json
disallowed_files:
  - .claude/**
  - plugins/prd-os/**
  - .prd-os/**
  - q-consult/**
  - q-system/.q-system/scripts/slack-notify.sh
  - plugins/kipi-core/skills/**
required_checks:
  - python3 -m pytest -q q-system/.q-system/tests/test_weekly_improve.py
required_reviews: []
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/test_weekly_improve.py -k 'masked or refused'"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-morning-brief-learns-2026-09-01 finding=finding-18 at=2026-09-01T22:00:59Z -->

# Friction artifact with ids and redaction, weekly pass via slack_founder, empty distinct from broken

## Context

Parent PRD: `.prd-os/prds/prd-morning-brief-learns-2026-09-01.md`

## Acceptance

RED first: (1) friction-note.sh assigns an id fr-<date>-<n>, refuses a line containing an email address (exit 1), and refuses when roadmap_scope says roadmap or unknown; (2) weekly-improve.py over an empty friction.jsonl renders 'nothing this week', over an unreadable one renders COULD NOT READ, and the two strings differ; (3) one friction line yields a proposal citing its id and a 60-character excerpt with emails masked, and a source-text assertion that the whole line never appears in the delivered message; (4) delivery goes through slack_founder.deliver; a source-text test asserts slack-notify.sh is never referenced; (5) a roadmap line that reached the file anyway is refused at read time. friction.jsonl lives under q-system/memory/ (instance-owned); the writer creates it on a fresh instance. Tests use tmp_path, never the live memory dir.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Friction artifact with ids and redaction, weekly pass via slack_founder, empty distinct from broken
