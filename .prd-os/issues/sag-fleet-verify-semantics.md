---
id: sag-fleet-verify-semantics
title: fleet-capability-verify.py: per-instance green/red/SKIPPED(standalone, reason printed); standalone entries (no q-system/.q-system) never silently pass
status: open
priority: p1
parent_prd: prd-silent-absence-capability-gate-2026-07-23
allowed_files:
  - fleet-capability-verify.py
disallowed_files: []
required_checks:
  - python3 fleet-capability-verify.py --self-test
required_reviews: []
bypass_exempt: "fleet verifier is skeleton-local tooling; its own --self-test is the no-bypass proof and gates.jsonl must not depend on 24 external repos being reachable"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-silent-absence-capability-gate-2026-07-23 finding=finding-3 at=2026-07-23T20:57:32Z -->

# fleet-capability-verify.py: per-instance green/red/SKIPPED(standalone, reason printed); standalone entries (no q-system/.q-system) never silently pass

## Context

Parent PRD: `.prd-os/prds/prd-silent-absence-capability-gate-2026-07-23.md`

## Acceptance

<!-- fill in -->

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] fleet-capability-verify.py: per-instance green/red/SKIPPED(standalone, reason printed); standalone entries (no q-system/.q-system) never silently pass
