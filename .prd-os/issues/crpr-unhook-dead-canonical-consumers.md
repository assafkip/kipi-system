---
id: crpr-unhook-dead-canonical-consumers
title: Stop requiring the dead tree, then delete the skeleton's plugin copy
status: open
priority: p0
parent_prd: prd-canonical-read-path-repair-2026-08-22
allowed_files:
  - q-system/.q-system/scripts/verify-containment-export.py
  - q-system/.q-system/scripts/test/test-verify-containment-export.sh
  - plugins/kipi-core/kipi-mcp/canonical/**
disallowed_files:
  - .claude/**
  - .prd-os/**
required_checks:
  - bash q-system/.q-system/scripts/test/test-verify-containment-export.sh
required_reviews:
  - runtime-owner
bypass_check: "bash q-system/.q-system/scripts/test/test-verify-containment-export.sh"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-canonical-read-path-repair-2026-08-22 finding=finding-22 at=2026-08-22T20:07:44Z -->

# Stop requiring the dead tree, then delete the skeleton's plugin copy

## Context

Parent PRD: `.prd-os/prds/prd-canonical-read-path-repair-2026-08-22.md`

## Acceptance

THREE hardcoded consumers, not two. Beyond EXPECTED_EXPORT_PATHS:24-28, RECEIPT_RELATIVE_PATH:30-32 is q-system/canonical/.containment-receipt.json and is loaded BEFORE any export path is validated, so the deletion breaks it first (finding-22). Define the receipt schema change explicitly (finding-7, finding-23): _validate_file_receipt requires source_path == destination_path AND membership in EXPECTED_EXPORT_PATHS, while the source is read as a git blob from the skeleton commit and the destination from the instance owner root - so repointing both to q-consult makes the source blob absent and repointing one violates the equality check. The spec must state the new source/destination split and bump the receipt schema_version. The required_check is a NEW harness because the bare script cannot run: it requires --instance and exits 2 on argparse (finding-2, finding-24); the harness must invoke it with a real instance and must FAIL if given a default. Prove exit 0 against an instance whose canonical lives outside q-system/. Only after that: git rm the SKELETON plugins/kipi-core/kipi-mcp/canonical/ tree, because plugins/ is mirrored with rsync -a --delete --delete-excluded (kipi-update.sh:2460) and deleting it elsewhere regenerates it.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Stop requiring the dead tree, then delete the skeleton's plugin copy
