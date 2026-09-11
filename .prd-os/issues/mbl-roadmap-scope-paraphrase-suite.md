---
id: mbl-roadmap-scope-paraphrase-suite
title: The roadmap boundary holds against a paraphrase suite run through every consumer
status: closed
priority: p1
parent_prd: prd-morning-brief-learns-2026-09-01
allowed_files:
  - q-system/.q-system/tests/fixtures/roadmap_scope_cases.json
  - q-system/.q-system/tests/test_roadmap_scope_suite.py
  - q-system/.q-system/capability/expected_tests/q-system__.q-system__tests__test_roadmap_scope_suite.py.json
  - q-system/.q-system/scripts/roadmap_scope.py
disallowed_files:
  - .claude/**
  - plugins/prd-os/**
  - .prd-os/**
  - q-consult/**
required_checks:
  - python3 -m pytest -q q-system/.q-system/tests/test_roadmap_scope_suite.py
required_reviews: []
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/test_roadmap_scope_suite.py -k paraphrases"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-morning-brief-learns-2026-09-01 finding=finding-12 at=2026-09-01T22:00:59Z -->

# The roadmap boundary holds against a paraphrase suite run through every consumer

## Context

Parent PRD: `.prd-os/prds/prd-morning-brief-learns-2026-09-01.md`

## Acceptance

A fixture file with at least 12 roadmap paraphrases covering product, pricing, publishing and client advice (none containing the literal words 'product' or 'roadmap') and at least 6 legitimate system proposals. RED first: the suite runs the SAME fixtures through roadmap_scope.classify AND through each consumer's refusal path (weekly-improve, improve_ground) by import, asserting every roadmap case is refused and every system case passes. Pattern lists may be extended in roadmap_scope.py to make the suite green; a case may not be deleted to make it green.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] The roadmap boundary holds against a paraphrase suite run through every consumer (16 roadmap + 11 system cases from a fixture; consumers derived from their owning issue specs, absent allowed only while the owner is open; 4 Codex findings accepted and patched)
