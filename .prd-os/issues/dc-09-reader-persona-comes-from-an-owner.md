---
id: dc-09-reader-persona-comes-from-an-owner
title: The reader persona is read from an owners file and its sha rides on every row
status: in-progress
priority: p1
parent_prd: prd-design-chain-seal-reads-verdicts-2026-09-18
allowed_files:
  - q-system/.q-system/capability/expected_tests/*
  - q-system/.q-system/scripts/design-chain-gate.py
  - q-system/.q-system/scripts/design-reader-gate.py
  - q-system/.q-system/scripts/test/test_dc_reader_persona.py
  - q-system/.q-system/scripts/test/test_dc_reader_verdicts.py
  - q-system/.q-system/scripts/test/test_dc_reader_gate.py
  - q-system/.q-system/scripts/test/test_dc_reader_gate_serves_itself.py
  - q-system/.q-system/scripts/test/test_dc_served_round_binds_what_it_serves.py
disallowed_files: []
required_checks:
  - python3 q-system/.q-system/scripts/test/test_dc_reader_persona.py
required_reviews: []
bypass_check: "python3 q-system/.q-system/scripts/test/test_dc_reader_persona.py"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-design-chain-seal-reads-verdicts-2026-09-18 finding=finding-8 at=2026-09-18T20:21:26Z -->

# The reader persona is read from an owners file and its sha rides on every row

## Context

Parent PRD: `.prd-os/prds/prd-design-chain-seal-reads-verdicts-2026-09-18.md`

## Acceptance

design-chain.json names readers.persona_file, which must be one of the files under owners; anything else is refused. Rows carry persona_sha256 and seal ignores rows whose persona sha differs from the live file.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] The reader persona is read from an owners file and its sha rides on every row
