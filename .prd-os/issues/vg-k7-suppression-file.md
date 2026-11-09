---
id: vg-k7-suppression-file
title: One bounded per-instance voice suppression file, read by every voice marker reader
status: in-progress
priority: p1
parent_prd: prd-voicegate-skeleton-2026-11-09
allowed_files:
  - q-system/.q-system/scripts/voice_suppressions.py
  - q-system/.q-system/scripts/voice-lint.py
  - q-system/.q-system/scripts/voice-substance-lint.py
  - q-system/.q-system/scripts/voiceloop-band-lint.py
  - q-system/.q-system/scripts/test/test_voice_suppressions.py
  - q-system/.q-system/scripts/test/test_voiceloop_band_lint.py
  - q-system/.q-system/capability/expected_tests/q-system__.q-system__scripts__test__test_voice_suppressions.py.json
disallowed_files: []
required_checks:
  - python3 -m pytest -q q-system/.q-system/scripts/test/test_voice_suppressions.py
  - python3 -m pytest -q q-system/.q-system/scripts/test/test_voiceloop_band_lint.py
required_reviews: []
bypass_check: "python3 -m pytest -q q-system/.q-system/scripts/test/test_voice_suppressions.py"
gate_lifecycle: historical-receipt
deliverables_count: 5
---
<!-- generated-by: prd_split.py prd=prd-voicegate-skeleton-2026-11-09 finding=finding-8 at=2026-11-09T18:24:23Z -->

# One bounded per-instance voice suppression file, read by every voice marker reader

## Context

Parent PRD: `.prd-os/prds/prd-voicegate-skeleton-2026-11-09.md`

## Acceptance

Row contract and discovery as in the PRD sections 'K7 row contract' and 'Shared discovery rule'. voice_suppressions.py is the single reader; the lints never parse the file themselves. Also run every existing test that imports or shells voice-lint.py or voice-substance-lint.py, found by grep at build time.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Red first: a file-listed path is skipped by voice-lint.py; an expired row does not skip
- [ ] A bad file or row suppresses nothing, is reported by name and never exits 1: malformed JSON, missing owner, missing reason, bad date, expires equal to today, expires more than 30 days after created, a glob path, an absolute path
- [ ] voice-lint.py, voice-substance-lint.py and voiceloop-band-lint.py call the reader; every skip prints owner, reason and expiry
- [ ] In an instance that has the file, in-file voice markers no longer skip and the lint says so; without the file, markers behave as today
- [ ] Census test: every script under q-system/.q-system/scripts that defines a voice skip marker imports the reader
