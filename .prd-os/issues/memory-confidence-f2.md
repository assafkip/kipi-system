---
id: memory-confidence-f2
title: mcp-03 build-order dependency stated and enforced by the wiring test
status: closed
priority: p1
parent_prd: prd-memory-confidence-provenance-2026-06-30
allowed_files:
  - .claude/settings.json
  - .claude/rules/skill-hook-pairing.md
  - q-system/.q-system/scripts/test_memory_confidence_wiring.py
disallowed_files: []
required_checks:
  - python3 q-system/.q-system/scripts/test_memory_confidence_wiring.py
required_reviews: []
bypass_check: "python3 q-system/.q-system/scripts/test_memory_confidence_wiring.py"
---
<!-- generated-by: prd_split.py prd=prd-memory-confidence-provenance-2026-06-30 finding=finding-2 at=2026-06-30T20:04:55Z -->

# mcp-03 build-order dependency stated and enforced by the wiring test

## Context

Parent PRD: `.prd-os/prds/prd-memory-confidence-provenance-2026-06-30.md`

## Acceptance

wiring test asserts both scripts exist (build-order) before checking settings.json entries; dependency also stated in Resolved decisions; pairing registered.
