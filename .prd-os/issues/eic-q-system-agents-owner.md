---
id: eic-q-system-agents-owner
title: Create and verify the q-system AGENTS ownership boundary
status: open
priority: p1
parent_prd: prd-enforcement-instruction-contract-2026-07-24
allowed_files:
  - q-system/AGENTS.md
  - tests/test_agents_imports.py
disallowed_files:
  - AGENTS.md
  - q-system/canonical/**
  - instance-registry.json
  - .prd-os/**
required_checks:
  - python3 -m pytest -q tests/test_agents_imports.py
required_reviews:
  - instruction-owner
bypass_check: "python3 -m pytest -q tests/test_agents_imports.py -k missing_import"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-enforcement-instruction-contract-2026-07-24 finding=finding-5 at=2026-07-24T21:10:19Z -->

# Create and verify the q-system AGENTS ownership boundary

## Context

Parent PRD: `.prd-os/prds/prd-enforcement-instruction-contract-2026-07-24.md`

## Acceptance

Write the failing missing-import test first. Put q-system path guidance in q-system/AGENTS.md and prove every repository import resolves in a fresh clone.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Create and verify the q-system AGENTS ownership boundary
