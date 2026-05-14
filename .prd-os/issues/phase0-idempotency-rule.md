---
id: phase0-idempotency-rule
title: Document idempotency contract for receipt writes in issue_runner.py
status: closed
priority: p2
parent_prd: prd-prd-os-receipts-and-phase0-measure-2026-05-14
allowed_files:
  - plugins/prd-os/scripts/issue_runner.py
disallowed_files: []
required_checks:
  - grep -q 'idempotent' plugins/prd-os/scripts/issue_runner.py
required_reviews: []
---
<!-- generated-by: prd_split.py prd=prd-prd-os-receipts-and-phase0-measure-2026-05-14 finding=finding-3 at=2026-05-14T16:14:57Z -->

# Document idempotency contract for receipt writes in issue_runner.py

## Context

Parent PRD: `.prd-os/prds/prd-prd-os-receipts-and-phase0-measure-2026-05-14.md`

## Acceptance

cmd_close docstring (or nearby comment block) documents the (prd_id, finding_id) idempotency key and explains concurrent / rerun behavior inline.
