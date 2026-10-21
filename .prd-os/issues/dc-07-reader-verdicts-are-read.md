---
id: dc-07-reader-verdicts-are-read
title: Reader rows carry a forced-choice verdict and seal refuses on LEAVE without a founder disposition
status: closed
priority: p1
parent_prd: prd-design-chain-seal-reads-verdicts-2026-09-18
allowed_files:
  - q-system/.q-system/capability/expected_tests/*
  - q-system/.q-system/scripts/design-chain-gate.py
  - q-system/.q-system/scripts/design-reader-gate.py
  - q-system/.q-system/scripts/test/test_dc_reader_verdicts.py
  - q-system/.q-system/scripts/test/fixtures/design-chain/*
  - q-system/.q-system/scripts/test/test_dc_reader_gate.py
  - q-system/.q-system/scripts/test/test_dc_reader_gate_serves_itself.py
  - q-system/.q-system/scripts/test/test_dc_served_round_binds_what_it_serves.py
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


Round A's reader rows are captured from design-reader-gate.py with the injected runner, provenance runner=injected: honest, and what dc-07 tests is how seal consumes verdicts, not what a model says. Condition, with its own RED FIRST: seal refuses a row whose provenance says runner=injected in any round that is not a test fixture, or the injected runner becomes the new way to hand-type verdicts (Sana, 2026-09-19).


Prompt injection through page text (dc-06 adversarial finding-6, Sana 2026-09-19): a control page carrying planted text that instructs the reader to answer STAY and 'unknown' must not seal. The acceptance test plants it and shows the judge refuses.

Design (Sana, 2026-09-19): the reader gate appends two fixed questions before the control, "VERDICT: answer exactly STAY or LEAVE" and "LABEL: pick exactly one of: <readers.labels>"; exact-match parse, anything else is not answered. Config: readers.labels required when readers is present, readers.narrow optional, readers.floor default 1.0. Seal requires reader rows only when design-chain.json has a readers block. Rows count only when page matches and html_sha256 equals the snapshot's page sha; none = refuse; a contaminated row is not answered. Reader id `<page>@<W>x<H>#<n>`; dispositions in gate/dispositions.md (forgeable by the builder; ASK-1834 is the backstop). runner=injected rows are honored only for a round under tempfile.gettempdir(). The prompt-injection control is one real run captured as a provenanced fixture that refuses at seal, plus an assertion on the FRAME text.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] Reader rows carry a forced-choice verdict and seal refuses on LEAVE without a founder disposition

## Amendments

### 2026-09-19T09:48:38Z
Reason: Sana 2026-09-19: add test/fixtures/design-chain/* for captured reader-row fixtures; record D1-D8 design picks

Before:
- allowed_files: ['q-system/.q-system/capability/expected_tests/*', 'q-system/.q-system/scripts/design-chain-gate.py', 'q-system/.q-system/scripts/design-reader-gate.py', 'q-system/.q-system/scripts/test/test_dc_reader_verdicts.py']
- required_checks: ['python3 q-system/.q-system/scripts/test/test_dc_reader_verdicts.py']
- disallowed_files: []

After:
- allowed_files: ['q-system/.q-system/capability/expected_tests/*', 'q-system/.q-system/scripts/design-chain-gate.py', 'q-system/.q-system/scripts/design-reader-gate.py', 'q-system/.q-system/scripts/test/test_dc_reader_verdicts.py', 'q-system/.q-system/scripts/test/fixtures/design-chain/*']
- required_checks: ['python3 q-system/.q-system/scripts/test/test_dc_reader_verdicts.py']
- disallowed_files: []

### 2026-09-19T09:50:28Z
Reason: the reader gate now asks two forced-choice questions (11 answers, readers.labels required), which legitimately breaks the three existing reader-gate tests; Sana's standing rule approves amends for tests a change legitimately breaks

Before:
- allowed_files: ['q-system/.q-system/capability/expected_tests/*', 'q-system/.q-system/scripts/design-chain-gate.py', 'q-system/.q-system/scripts/design-reader-gate.py', 'q-system/.q-system/scripts/test/test_dc_reader_verdicts.py', 'q-system/.q-system/scripts/test/fixtures/design-chain/*']
- required_checks: ['python3 q-system/.q-system/scripts/test/test_dc_reader_verdicts.py']
- disallowed_files: []

After:
- allowed_files: ['q-system/.q-system/capability/expected_tests/*', 'q-system/.q-system/scripts/design-chain-gate.py', 'q-system/.q-system/scripts/design-reader-gate.py', 'q-system/.q-system/scripts/test/test_dc_reader_verdicts.py', 'q-system/.q-system/scripts/test/fixtures/design-chain/*', 'q-system/.q-system/scripts/test/test_dc_reader_gate.py', 'q-system/.q-system/scripts/test/test_dc_reader_gate_serves_itself.py', 'q-system/.q-system/scripts/test/test_dc_served_round_binds_what_it_serves.py']
- required_checks: ['python3 q-system/.q-system/scripts/test/test_dc_reader_verdicts.py']
- disallowed_files: []
