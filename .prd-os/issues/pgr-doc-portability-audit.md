---
id: pgr-doc-portability-audit
title: Audit canonical runbooks for stale and nonportable references
status: open
priority: p2
parent_prd: prd-portable-generated-runbooks-2026-07-24
allowed_files:
  - scripts/doc-portability-audit.py
  - README.md
  - SETUP.md
  - ARCHITECTURE.md
  - CONTRIBUTE.md
  - tests/test_doc_portability.py
disallowed_files:
  - q-system/output/**
  - q-system/canonical/**
  - instance-registry.json
  - .prd-os/**
required_checks:
  - python3 -m pytest -q tests/test_doc_portability.py
  - python3 scripts/doc-portability-audit.py
required_reviews:
  - docs-owner
bypass_check: "python3 -m pytest -q tests/test_doc_portability.py -k 'missing_import or absolute_path or retired'"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-portable-generated-runbooks-2026-07-24 finding=finding-4 at=2026-07-24T21:13:00Z -->

# Audit canonical runbooks for stale and nonportable references

## Context

Parent PRD: `.prd-os/prds/prd-portable-generated-runbooks-2026-07-24.md`

## Acceptance

Write failing missing-import, stale-absolute-path, retired-instance, and old-repository fixtures first. Correct current setup instructions without rewriting historical records.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Audit canonical runbooks for stale and nonportable references
