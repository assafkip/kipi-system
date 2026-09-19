---
id: dc-07-reader-verdicts-are-read
title: Reader rows carry a forced-choice verdict and seal refuses on LEAVE without a founder disposition
status: open
priority: p1
parent_prd: prd-design-chain-seal-reads-verdicts-2026-09-18
allowed_files:
  - q-system/.q-system/capability/expected_tests/*
  - q-system/.q-system/scripts/design-chain-gate.py
  - q-system/.q-system/scripts/design-reader-gate.py
  - q-system/.q-system/scripts/test/test_dc_reader_verdicts.py
disallowed_files: []
required_checks:
  - python3 q-system/.q-system/scripts/test/test_dc_reader_verdicts.py
required_reviews: []
bypass_check: "python3 q-system/.q-system/scripts/test/test_dc_reader_verdicts.py"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-design-chain-seal-reads-verdicts-2026-09-18 finding=finding-19 at=2026-09-18T20:21:26Z -->

# Reader rows carry a forced-choice verdict and seal refuses on LEAVE without a founder disposition

## Context

Parent PRD: `.prd-os/prds/prd-design-chain-seal-reads-verdicts-2026-09-18.md`

## Acceptance

Each row has verdict in {STAY, LEAVE} and a what_he_sells label parsed from a forced-choice final question; an unparseable answer counts as not answered. seal applies a floor (answered out of attempted, from config) and refuses on any LEAVE or a label in the narrow list unless '- reader <id>: FOUNDER <reason>' exists. Negative control: RCA round A refuses naming the readers.


The RED FIRST test is round A (dc_fixtures, with provenance): it seals before this change and refuses after, naming the readers. (Sana, 2026-09-19, moved from dc-21.)

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Reader rows carry a forced-choice verdict and seal refuses on LEAVE without a founder disposition
