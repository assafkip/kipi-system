---
id: dr-one-provenance-vocabulary-2026-07-28
title: One provenance vocabulary with defined composition, read from one table by both validators
status: open
priority: p1
parent_prd: prd-deterministic-reading-2026-07-28
allowed_files:
  - q-system/.q-system/scripts/provenance_vocabulary.py
  - q-system/.q-system/scripts/provenance-vocabulary.json
  - q-system/.q-system/scripts/test_provenance_vocabulary.py
  - .claude/rules/evidence-ledger.md
disallowed_files: []
required_checks:
  - python3 q-system/.q-system/scripts/test_provenance_vocabulary.py
required_reviews: []
bypass_check: "grep -q 'provenance_vocabulary' q-system/.q-system/scripts/handoff-provenance-lint.py && grep -q 'provenance_vocabulary' q-system/.q-system/scripts/memory-confidence-validator.py"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-deterministic-reading-2026-07-28 finding=finding-7 at=2026-07-28T22:58:38Z -->

# One provenance vocabulary with defined composition, read from one table by both validators

## Context

Parent PRD: `.prd-os/prds/prd-deterministic-reading-2026-07-28.md`

## Acceptance

The three forms are ranked rather than merely listed: ev-<id> outranks every enum value, {{UNVERIFIED}} maps to provenance: inferred, and strongest() resolves a line carrying more than one. Both validators import the same module. Shipped 5bed187, extended in ASK-230.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] One provenance vocabulary with defined composition, read from one table by both validators
