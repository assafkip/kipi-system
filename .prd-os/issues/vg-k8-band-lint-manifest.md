---
id: vg-k8-band-lint-manifest
title: Band lint reads the instance voice-check.json; the engine still gets x or threads
status: in-progress
priority: p1
parent_prd: prd-voicegate-skeleton-2026-11-09
allowed_files:
  - q-system/.q-system/scripts/voiceloop-band-lint.py
  - q-system/.q-system/scripts/test/test_voiceloop_band_lint.py
  - q-system/.q-system/scripts/test/fixtures/voice-check/*
disallowed_files: []
required_checks:
  - python3 -m pytest -q q-system/.q-system/scripts/test/test_voiceloop_band_lint.py
required_reviews: []
bypass_exempt: "The band lint is DETECTED and exits 0 on every path by contract, so there is no gate to bypass. The red test pins the channel the engine receives."
deliverables_count: 5
---
<!-- generated-by: prd_split.py prd=prd-voicegate-skeleton-2026-11-09 finding=finding-6 at=2026-11-09T18:24:23Z -->

# Band lint reads the instance voice-check.json; the engine still gets x or threads

## Context

Parent PRD: `.prd-os/prds/prd-voicegate-skeleton-2026-11-09.md`

## Acceptance

Discovery and manifest contract as in the PRD sections 'Shared discovery rule' and 'K8 manifest contract'. The instance_q_dir is resolved by importing the resolver in evidence_ledger.py, not by a second copy.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] Red first: with a fixture manifest mapping surface x to lane short with engine_channel threads, an x draft runs review with channel threads (today it runs channel x)
- [x] The engine never receives a lane name: a test asserts the argv channel is one the table emits, and with the voiceloop package installed an over-length x draft still reports its length row
- [x] No manifest: the table result is unchanged (pinned)
- [x] Malformed or unreadable manifest, or an engine_channel outside the table: one reported line naming the file and reason, then the table (tested)
- [x] Manifest found by the shared discovery rule: CLAUDE_PROJECT_DIR else git toplevel, instance_q_dir from the evidence_ledger resolver
