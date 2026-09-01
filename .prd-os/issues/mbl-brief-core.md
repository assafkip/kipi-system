---
id: mbl-brief-core
title: One owner of morning-brief.py: three-item lead tier, guarded collectors, optional-section registry
status: in-progress
priority: p0
parent_prd: prd-morning-brief-learns-2026-09-01
allowed_files:
  - q-system/.q-system/scripts/morning-brief.py
  - q-system/.q-system/tests/test_morning_brief.py
  - q-system/.q-system/capability/expected_tests/q-system__.q-system__tests__test_morning_brief.py.json
disallowed_files:
  - .claude/**
  - plugins/prd-os/**
  - .prd-os/**
  - q-system/.q-system/scripts/voice-stop-gate.py
  - q-consult/**
required_checks:
  - python3 -m pytest -q q-system/.q-system/tests/test_morning_brief.py
required_reviews: []
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/test_morning_brief.py -k 'withheld or isolation or registry'"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-morning-brief-learns-2026-09-01 finding=finding-2 at=2026-09-01T22:00:59Z -->

# One owner of morning-brief.py: three-item lead tier, guarded collectors, optional-section registry

## Context

Parent PRD: `.prd-os/prds/prd-morning-brief-learns-2026-09-01.md`

## Acceptance

The ONLY entry that edits morning-brief.py or test_morning_brief.py. RED first, three groups: (1) WITHHELD: stage five owed items across DUE / owner:assaf / needs_founder loops; collect_owed returns provenance-tagged rows (source in {linear, loops}); the lead tier renders exactly three rows plus one row 'withheld N more: M in Linear, K in open-loops' derived from the tags (covers finding-15). (2) ISOLATION: monkeypatch one collector to raise RuntimeError('token=abc'); the other sections render; the failing one renders 'COULD NOT READ: <collector> failed (RuntimeError)' with NO exception message in the brief and the message in the local log (covers finding-14); degraded is True. (3) REGISTRY: OPTIONAL_SECTIONS = [(module_stem, key, title), ...]; a present module runs through the same guard within a 20-second budget; an absent module renders no section and writes one log line; a test enumerates SECTIONS + OPTIONAL_SECTIONS and asserts each is guarded. Add the missing capability fragment for test_morning_brief.py.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] One owner of morning-brief.py: three-item lead tier, guarded collectors, optional-section registry
