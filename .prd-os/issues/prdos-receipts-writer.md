---
id: prdos-receipts-writer
title: Fix cmd_close to write to .prd-os/receipts.jsonl
status: closed
priority: p0
parent_prd: prd-prd-os-receipts-and-phase0-measure-2026-05-14
allowed_files:
  - plugins/prd-os/scripts/issue_runner.py
  - plugins/prd-os/tests/test_issue_runner.py
disallowed_files: []
required_checks:
  - pytest -q plugins/prd-os/tests/test_issue_runner.py
required_reviews:
  - codex-review
---
<!-- generated-by: prd_split.py prd=prd-prd-os-receipts-and-phase0-measure-2026-05-14 finding=finding-1 at=2026-05-14T16:14:57Z -->

# Fix cmd_close to write to .prd-os/receipts.jsonl

## Context

Parent PRD: `.prd-os/prds/prd-prd-os-receipts-and-phase0-measure-2026-05-14.md`

## Acceptance

cmd_close appends a {prd_id, finding_id, issue_id, closed_at, receipts} record to cfg.receipts_path after status flip, before state clear. Idempotent on (prd_id, finding_id). MARKER_RE from prd_split.py imported and used to recover finding_id. New tests cover: success path, parent-dir creation, marker-missing warning, end-to-end unblock of /prd-archive.
