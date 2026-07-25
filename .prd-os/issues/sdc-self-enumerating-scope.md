---
id: sdc-self-enumerating-scope
title: Enumerate the containment scope from repository state
status: closed
priority: p0
parent_prd: prd-skeleton-data-containment-2026-07-24
allowed_files:
  - q-system/.q-system/scripts/containment-targets.py
  - q-system/.q-system/tests/separation/test_containment_targets.py
  - validate-separation.py
disallowed_files:
  - q-system/canonical/**
  - instance-registry.json
  - .prd-os/**
required_checks:
  - python3 -m pytest -q q-system/.q-system/tests/separation/test_containment_targets.py
required_reviews:
  - repository-owner
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/separation/test_containment_targets.py -k new_tracked_surface"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-skeleton-data-containment-2026-07-24 finding=finding-11 at=2026-07-24T20:50:23Z -->

# Enumerate the containment scope from repository state

## Context

Parent PRD: `.prd-os/prds/prd-skeleton-data-containment-2026-07-24.md`

## Acceptance

Write a failing new-surface test first. Derive tracked text targets from Git and validate explicit exclusions for PRD state, output, memory, generated assets, and binaries.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] Enumerate the containment scope from repository state

## Amendments

### 2026-07-24T22:14:43Z
Reason: Founder approved validate-separation.py production wiring so repository-derived containment targets reach the semantic separation gate

Before:
- allowed_files: ['q-system/.q-system/scripts/containment-targets.py', 'q-system/.q-system/tests/separation/test_containment_targets.py']
- required_checks: ['python3 -m pytest -q q-system/.q-system/tests/separation/test_containment_targets.py']
- disallowed_files: ['validate-separation.py', 'q-system/canonical/**', 'instance-registry.json', '.prd-os/**']

After:
- allowed_files: ['q-system/.q-system/scripts/containment-targets.py', 'q-system/.q-system/tests/separation/test_containment_targets.py', 'validate-separation.py']
- required_checks: ['python3 -m pytest -q q-system/.q-system/tests/separation/test_containment_targets.py']
- disallowed_files: ['q-system/canonical/**', 'instance-registry.json', '.prd-os/**']
