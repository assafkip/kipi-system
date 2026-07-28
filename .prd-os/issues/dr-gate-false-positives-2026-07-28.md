---
id: dr-gate-false-positives-2026-07-28
title: Fix the three false positives that made the shipped grounding gates unusable
status: open
priority: p0
parent_prd: prd-deterministic-reading-2026-07-28
allowed_files:
  - q-system/.q-system/scripts/handoff-provenance-lint.py
  - q-system/.q-system/scripts/client-output-evidence-gate.py
  - q-system/.q-system/scripts/evidence_ledger.py
  - q-system/.q-system/scripts/test_handoff_provenance_lint.py
  - q-system/.q-system/scripts/test_client_output_evidence_gate.py
disallowed_files: []
required_checks:
  - python3 q-system/.q-system/scripts/test_handoff_provenance_lint.py
  - python3 q-system/.q-system/scripts/test_client_output_evidence_gate.py
  - python3 q-system/.q-system/scripts/test_evidence_ledger.py
required_reviews: []
bypass_check: "grep -q 'HEADER_RE' q-system/.q-system/scripts/handoff-provenance-lint.py && grep -q 'def adopted' q-system/.q-system/scripts/evidence_ledger.py && grep -q 'ISO_DATE_RE' q-system/.q-system/scripts/evidence_ledger.py"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-deterministic-reading-2026-07-28 finding=finding-1 at=2026-07-28T22:58:38Z -->

# Fix the three false positives that made the shipped grounding gates unusable

## Context

Parent PRD: `.prd-os/prds/prd-deterministic-reading-2026-07-28.md`

## Acceptance

Dated markdown headers pass the handoff lint while dated CLAIMS and numbers-in-headers still block; ISO dates and bare years are not measurements while a real count on the same line still blocks; an absent evidence.jsonl is a no-op while one row restores full enforcement. Each fix ships with its negative case. ASK-231, ASK-232, ASK-233.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Fix the three false positives that made the shipped grounding gates unusable
