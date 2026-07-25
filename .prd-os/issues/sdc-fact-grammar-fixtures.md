---
id: sdc-fact-grammar-fixtures
title: Specify fact and template grammar fixtures
status: closed
priority: p0
parent_prd: prd-skeleton-data-containment-2026-07-24
allowed_files:
  - q-system/.q-system/tests/separation/fixtures/fact-grammar.json
  - q-system/.q-system/tests/separation/test_fact_grammar.py
disallowed_files:
  - validate-separation.py
  - q-system/canonical/**
  - instance-registry.json
  - .prd-os/**
required_checks:
  - python3 -m pytest -q q-system/.q-system/tests/separation/test_fact_grammar.py
required_reviews:
  - security
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/separation/test_fact_grammar.py -k boundary"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-skeleton-data-containment-2026-07-24 finding=finding-10 at=2026-07-24T20:50:23Z -->

# Specify fact and template grammar fixtures

## Context

Parent PRD: `.prd-os/prds/prd-skeleton-data-containment-2026-07-24.md`

## Acceptance

Write failing boundary cases first. Cover populated fields, sourced dated interactions, currency, case facts, placeholders, synthetic markers, and unclassified fail-closed behavior.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] Specify fact and template grammar fixtures
