---
id: dc-14-founder-findings-close
title: A FOUNDER-FINDING[tag] line needs a disposition before seal
status: in-progress
priority: p1
parent_prd: prd-design-chain-seal-reads-verdicts-2026-09-18
allowed_files:
  - q-system/.q-system/capability/expected_tests/*
  - q-system/.q-system/scripts/design-chain-gate.py
  - q-system/.q-system/scripts/test/test_dc_founder_findings.py
disallowed_files: []
required_checks:
  - python3 q-system/.q-system/scripts/test/test_dc_founder_findings.py
required_reviews: []
bypass_check: "python3 q-system/.q-system/scripts/test/test_dc_founder_findings.py"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-design-chain-seal-reads-verdicts-2026-09-18 finding=finding-20 at=2026-09-18T20:21:26Z -->

# A FOUNDER-FINDING[tag] line needs a disposition before seal

## Context

Parent PRD: `.prd-os/prds/prd-design-chain-seal-reads-verdicts-2026-09-18.md`

## Acceptance

Reuses WEAK_RE and DISPOSITION_RE machinery. An undisposed FOUNDER-FINDING[tag] in any round file refuses the seal.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] A FOUNDER-FINDING[tag] line needs a disposition before seal
