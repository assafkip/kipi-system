---
id: memory-confidence-f1
title: Trust signal reaches every reader: surfacer + direct-Read field + MEMORY.md [low-conf] marker
status: closed
priority: p1
parent_prd: prd-memory-confidence-provenance-2026-06-30
allowed_files:
  - q-system/.q-system/scripts/memory-confidence-surface.py
  - q-system/.q-system/scripts/test_memory_confidence_surface.py
  - q-system/.q-system/scripts/memory-confidence-validator.py
  - q-system/.q-system/scripts/test_memory_confidence_validator.py
  - .claude/rules/memory-confidence.md
disallowed_files: []
required_checks:
  - python3 q-system/.q-system/scripts/test_memory_confidence_surface.py
  - python3 q-system/.q-system/scripts/test_memory_confidence_validator.py
required_reviews: []
bypass_check: "python3 q-system/.q-system/scripts/test_memory_confidence_surface.py"
---
<!-- generated-by: prd_split.py prd=prd-memory-confidence-provenance-2026-06-30 finding=finding-1 at=2026-06-30T20:04:55Z -->

# Trust signal reaches every reader: surfacer + direct-Read field + MEMORY.md [low-conf] marker

## Context

Parent PRD: `.prd-os/prds/prd-memory-confidence-provenance-2026-06-30.md`

## Acceptance

low-trust memory surfaces at SessionStart; the field is visible on any direct Read; MEMORY.md [low-conf] marker convention documented in the rule; validator blocks invalid values at write (negative self-test proves teeth).
