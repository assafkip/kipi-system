---
id: pff-classifier-reach
title: State and measure how much of a leak the classifier can see
status: in-progress
priority: p0
parent_prd: prd-prevent-fact-fanout-2026-07-25
allowed_files:
  - q-system/.q-system/tests/separation/test_semantic_client_leakage.py
  - q-system/.q-system/tests/separation/fixtures/fact-grammar.json
disallowed_files:
  - kipi-update.sh
  - instance-registry.json
  - .prd-os/**
required_checks:
  - python3 -m pytest -q q-system/.q-system/tests/separation/test_semantic_client_leakage.py
required_reviews:
  - security
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/separation/test_semantic_client_leakage.py -k 'blind_spot and measured'"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-prevent-fact-fanout-2026-07-25 finding=finding-1 at=2026-07-25T18:11:12Z -->

# State and measure how much of a leak the classifier can see

## Context

Parent PRD: `.prd-os/prds/prd-prevent-fact-fanout-2026-07-25.md`

## Acceptance

Write the failing prose-leak fixture first. Pin the classifier's blind spots (prose, headings, JSON, code, config) as explicit RED fixtures so the coverage bound is measured and visible rather than assumed.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] State and measure how much of a leak the classifier can see
