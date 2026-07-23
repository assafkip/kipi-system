---
id: sag-core-gate-build
title: Build capability-gate.py + capability-manifest.json + paired tests + token-guard fixes (atomic decomposition anchor)
status: closed
priority: p0
parent_prd: prd-silent-absence-capability-gate-2026-07-23
allowed_files:
  - q-system/.q-system/scripts/capability-gate.py
  - q-system/.q-system/capability-manifest.json
  - q-system/.q-system/scripts/test_capability_gate.py
  - q-system/.q-system/token-guard.py
  - q-system/.q-system/scripts/test_token_guard_observation.py
  - q-system/.q-system/scripts/**
disallowed_files: []
required_checks:
  - python3 q-system/.q-system/scripts/test_capability_gate.py
  - python3 q-system/.q-system/scripts/test_token_guard_observation.py
required_reviews: []
bypass_check: "python3 q-system/.q-system/scripts/capability-gate.py --check-only"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-silent-absence-capability-gate-2026-07-23 finding=finding-1 at=2026-07-23T20:57:32Z -->

# Build capability-gate.py + capability-manifest.json + paired tests + token-guard fixes (atomic decomposition anchor)

## Context

Parent PRD: `.prd-os/prds/prd-silent-absence-capability-gate-2026-07-23.md`

## Acceptance

Gate discovers all three conventions, runs them as subprocesses, diffs both directions; manifest declares all four sets; token-guard has observation exemption + stall-warn rate limit with paired tests.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Build capability-gate.py + capability-manifest.json + paired tests + token-guard fixes (atomic decomposition anchor)
