---
id: dsse-deliverable-count-lock
title: deliverables_count in issue spec schema; closeout refuses on receipt mismatch
status: closed
priority: p1
parent_prd: prd-fable-discipline-2026-07-04
allowed_files:
  - plugins/kipi-dsse/scripts/**
  - plugins/kipi-dsse/hooks/**
  - plugins/kipi-dsse/commands/**
  - plugins/prd-os/scripts/prd_split.py
  - plugins/prd-os/templates/issue.md
  - plugins/prd-os/tests/**
disallowed_files: []
required_checks:
  - pytest -q plugins/kipi-dsse
  - pytest -q plugins/prd-os/tests
required_reviews: []
bypass_check: "pytest -q plugins/kipi-dsse"
---
<!-- generated-by: prd_split.py prd=prd-fable-discipline-2026-07-04 finding=finding-3 at=2026-07-04T01:45:32Z -->

# deliverables_count in issue spec schema; closeout refuses on receipt mismatch

## Context

Parent PRD: `.prd-os/prds/prd-fable-discipline-2026-07-04.md`

## Acceptance

deliverables_count locked at issue-start like allowed_files; closeout cross-checks receipts against the count and refuses on mismatch. Compat: specs without the field close under current rules (check skipped); prd_split.py writes the field on all new specs; malformed values rejected at issue-start. Red-then-green reproducer for the refusal path.
