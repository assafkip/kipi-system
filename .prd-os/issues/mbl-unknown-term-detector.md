---
id: mbl-unknown-term-detector
title: Unknown-term section with normalization, allowlists and a precision fixture
status: open
priority: p1
parent_prd: prd-morning-brief-learns-2026-09-01
allowed_files:
  - q-system/.q-system/scripts/unknown_terms.py
  - q-system/.q-system/tests/test_unknown_terms.py
  - q-system/.q-system/tests/fixtures/unknown_terms_precision.json
  - q-system/.q-system/capability/expected_tests/q-system__.q-system__tests__test_unknown_terms.py.json
disallowed_files:
  - .claude/**
  - plugins/prd-os/**
  - .prd-os/**
  - q-consult/**
  - q-system/canonical/**
  - q-system/.q-system/scripts/morning-brief.py
required_checks:
  - python3 -m pytest -q q-system/.q-system/tests/test_unknown_terms.py
required_reviews: []
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/test_unknown_terms.py -k precision"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-morning-brief-learns-2026-09-01 finding=finding-13 at=2026-09-01T22:00:59Z -->

# Unknown-term section with normalization, allowlists and a precision fixture

## Context

Parent PRD: `.prd-os/prds/prd-morning-brief-learns-2026-09-01.md`

## Acceptance

A registered optional section (module stem unknown_terms, added to OPTIONAL_SECTIONS by issue mbl-brief-core in advance; this issue only provides the module). collect(now, payloads, canonical_dir) is pure over already-fetched calendar and mail payloads: no second pull. Normalization: drop sentence-initial capitalized words unless they recur mid-sentence, drop signature blocks, drop calendar attendee names and email local parts, drop a stopword list, drop any term present in canonical_dir. RED first: precision fixture with 5 planted unknowns and 10 planted decoys (attendee names, sentence starts, signature lines, common brands present in canonical); at least 4 of 5 surface and 0 decoys; cap is 5. Live evidence (one real unknown) recorded at closeout, not asserted by pytest.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Unknown-term section with normalization, allowlists and a precision fixture
