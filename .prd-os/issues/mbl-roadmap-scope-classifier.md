---
id: mbl-roadmap-scope-classifier
title: One deterministic roadmap-scope classifier, fail-closed, shared by every consumer
status: open
priority: p0
parent_prd: prd-morning-brief-learns-2026-09-01
allowed_files:
  - q-system/.q-system/scripts/roadmap_scope.py
  - q-system/.q-system/tests/test_roadmap_scope.py
  - q-system/.q-system/capability/expected_tests/q-system__.q-system__tests__test_roadmap_scope.py.json
disallowed_files:
  - .claude/**
  - plugins/prd-os/**
  - .prd-os/**
  - q-consult/**
required_checks:
  - python3 -m pytest -q q-system/.q-system/tests/test_roadmap_scope.py
required_reviews: []
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/test_roadmap_scope.py -k 'fail_closed or labelled_rule'"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-morning-brief-learns-2026-09-01 finding=finding-1 at=2026-09-01T22:00:59Z -->

# One deterministic roadmap-scope classifier, fail-closed, shared by every consumer

## Context

Parent PRD: `.prd-os/prds/prd-morning-brief-learns-2026-09-01.md`

## Acceptance

RED first: classify(text, declared_target) returns roadmap for a product proposal labelled target=rule (the exact bypass finding-1 names); returns unknown for empty text or an unrecognised target, and unknown is a refusal for every consumer; returns system for a rule/lint/trigger/context proposal. Pattern lists for product, pricing, publish, client-advice live in this module only. No LLM call, no network, importable, and a CLI `roadmap_scope.py --target X` that exits 0/2/3 for system/roadmap/unknown so friction-note.sh can call it.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] One deterministic roadmap-scope classifier, fail-closed, shared by every consumer
