---
id: sdc-owner-export
title: Export current facts to the verified investigations owner
status: closed
priority: p0
parent_prd: prd-skeleton-data-containment-2026-07-24
allowed_files:
  - q-system/.q-system/scripts/verify-containment-export.py
  - q-system/.q-system/tests/separation/test_containment_export.py
  - /Users/assafkipnis/projects/intel/projects/kipi-investigations/q-system/canonical/discovery.md
  - /Users/assafkipnis/projects/intel/projects/kipi-investigations/q-system/canonical/pricing-framework.md
  - /Users/assafkipnis/projects/intel/projects/kipi-investigations/q-system/canonical/.containment-receipt.json
disallowed_files:
  - q-system/canonical/**
  - instance-registry.json
  - .prd-os/**
  - .git/**
required_checks:
  - python3 q-system/.q-system/scripts/verify-containment-export.py --instance investigations
required_reviews:
  - data-owner
  - security
bypass_check: "python3 q-system/.q-system/scripts/verify-containment-export.py --instance investigations --require-hash-match"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-skeleton-data-containment-2026-07-24 finding=finding-6 at=2026-07-24T20:50:23Z -->

# Export current facts to the verified investigations owner

## Context

Parent PRD: `.prd-os/prds/prd-skeleton-data-containment-2026-07-24.md`

## Acceptance

Write a failing destination-receipt contract test first. Confirm the owner path, export the complete records, and record source and destination hashes before any skeleton source is restored.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] Export current facts to the verified investigations owner

## Amendments

### 2026-07-24T22:24:54Z
Reason: Required receipt command was a false-green no-op; add its deterministic verifier and missing-receipt contract test before the approved external export

Before:
- allowed_files: ['/Users/assafkipnis/projects/intel/projects/kipi-investigations/q-system/canonical/discovery.md', '/Users/assafkipnis/projects/intel/projects/kipi-investigations/q-system/canonical/pricing-framework.md', '/Users/assafkipnis/projects/intel/projects/kipi-investigations/q-system/canonical/.containment-receipt.json']
- required_checks: ['python3 q-system/.q-system/scripts/verify-containment-export.py --instance investigations']
- disallowed_files: ['q-system/canonical/**', 'instance-registry.json', '.prd-os/**', '.git/**']

After:
- allowed_files: ['q-system/.q-system/scripts/verify-containment-export.py', 'q-system/.q-system/tests/separation/test_containment_export.py', '/Users/assafkipnis/projects/intel/projects/kipi-investigations/q-system/canonical/discovery.md', '/Users/assafkipnis/projects/intel/projects/kipi-investigations/q-system/canonical/pricing-framework.md', '/Users/assafkipnis/projects/intel/projects/kipi-investigations/q-system/canonical/.containment-receipt.json']
- required_checks: ['python3 q-system/.q-system/scripts/verify-containment-export.py --instance investigations']
- disallowed_files: ['q-system/canonical/**', 'instance-registry.json', '.prd-os/**', '.git/**']
