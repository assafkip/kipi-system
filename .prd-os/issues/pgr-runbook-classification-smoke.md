---
id: pgr-runbook-classification-smoke
title: Classify runbooks and prove fresh-clone setup
status: open
priority: p2
parent_prd: prd-portable-generated-runbooks-2026-07-24
allowed_files:
  - runbooks.json
  - scripts/test-fresh-clone-setup.sh
  - tests/test_runbook_classification.py
disallowed_files:
  - q-system/output/**
  - instance-registry.json
  - .prd-os/**
  - .git/**
required_checks:
  - python3 -m pytest -q tests/test_runbook_classification.py
  - bash scripts/test-fresh-clone-setup.sh
required_reviews:
  - docs-owner
  - packaging-owner
bypass_check: "python3 -m pytest -q tests/test_runbook_classification.py -k 'unclassified or historical_as_current'"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-portable-generated-runbooks-2026-07-24 finding=finding-5 at=2026-07-24T21:13:00Z -->

# Classify runbooks and prove fresh-clone setup

## Context

Parent PRD: `.prd-os/prds/prd-portable-generated-runbooks-2026-07-24.md`

## Acceptance

Write a failing unclassified-doc and source-machine-path test first. Mark canonical versus historical docs and pass setup in a disposable fresh clone.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Classify runbooks and prove fresh-clone setup
