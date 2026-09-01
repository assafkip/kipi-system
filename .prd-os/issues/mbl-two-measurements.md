---
id: mbl-two-measurements
title: Permission-ask counter with a ledger, and decision-corpus cost with a stated formula
status: open
priority: p2
parent_prd: prd-morning-brief-learns-2026-09-01
allowed_files:
  - q-system/.q-system/scripts/permission-ask-counter.py
  - q-system/.q-system/scripts/decision-corpus-cost.py
  - q-system/.q-system/tests/test_permission_ask_counter.py
  - q-system/.q-system/tests/test_decision_corpus_cost.py
  - q-system/.q-system/capability/expected_tests/q-system__.q-system__tests__test_permission_ask_counter.py.json
  - q-system/.q-system/capability/expected_tests/q-system__.q-system__tests__test_decision_corpus_cost.py.json
  - q-system/output/plans/morning-brief-overhaul-2026-08-30.md
disallowed_files:
  - .claude/**
  - plugins/prd-os/**
  - .prd-os/**
  - q-consult/**
  - q-system/.q-system/scripts/voice-dna-loader.py
required_checks:
  - python3 -m pytest -q q-system/.q-system/tests/test_permission_ask_counter.py q-system/.q-system/tests/test_decision_corpus_cost.py
required_reviews: []
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/test_permission_ask_counter.py -k broken_apparatus_exits_3"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-morning-brief-learns-2026-09-01 finding=finding-16 at=2026-09-01T22:00:59Z -->

# Permission-ask counter with a ledger, and decision-corpus cost with a stated formula

## Context

Parent PRD: `.prd-os/prds/prd-morning-brief-learns-2026-09-01.md`

## Acceptance

RED first: (1) the counter over a fixture transcript with two pick-then-menu turns reports count 2 and appends one ledger line to q-system/output/permission-ask-ledger.jsonl; over an unreadable sample dir it exits 3 and appends nothing; (2) the cost script prints bytes and tokens = ceil(bytes / 4) with that formula in its output (finding-16: reproducible by construction; no tokenizer dependency) and exits 3 when KIPI_VOICE_DIR is unset. The measured live cost is written into the plan file's 2h section; voice-dna-loader.py is NOT modified and route_classifier.py is never imported.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Permission-ask counter with a ledger, and decision-corpus cost with a stated formula
