---
id: crpr-one-canonical-resolver
title: One fail-closed resolver for an instance canonical root
status: open
priority: p0
parent_prd: prd-canonical-read-path-repair-2026-08-22
allowed_files:
  - q-system/.q-system/scripts/evidence_ledger.py
  - q-system/.q-system/scripts/test_evidence_ledger.py
  - instance-registry.json
disallowed_files:
  - .claude/**
  - plugins/**
  - .prd-os/**
required_checks:
  - python3 q-system/.q-system/scripts/test_evidence_ledger.py
required_reviews:
  - runtime-owner
bypass_check: "python3 q-system/.q-system/scripts/test_evidence_ledger.py"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-canonical-read-path-repair-2026-08-22 finding=finding-16 at=2026-08-22T20:07:44Z -->

# One fail-closed resolver for an instance canonical root

## Context

Parent PRD: `.prd-os/prds/prd-canonical-read-path-repair-2026-08-22.md`

## Acceptance

Write the failing cases FIRST and show them RED. instance_root() must FAIL CLOSED, not guess, on all three measured gaps: (a) two named q-* dirs both containing canonical/ (today sorted()[0] silently wins, finding-17); (b) a resolved directory with no canonical/ subdir, measured on the two instances whose q-system holds no canonical/ (finding-18); (c) registry instance_q_dir disagreeing with the filesystem, the four instances where the registry says null while a real domain dir containing canonical/ exists (finding-16); enumerate them with the --audit-instance-roots command in the PRD rather than hardcoding names, since this repo is public. Fill in those four instance_q_dir values in instance-registry.json (the registry is gitignored-safe to name locally, the PRD is not) so registry and filesystem agree, and make the resolver read the registry as authority with the filesystem as a cross-check that RAISES on mismatch. NOTE the harness convention: this suite is main-based with case_* functions and pytest collects ZERO tests from it (finding-3, finding-29), so the required_check invokes it directly with python3; do NOT convert it to pytest as a way of making a check go green.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] One fail-closed resolver for an instance canonical root
