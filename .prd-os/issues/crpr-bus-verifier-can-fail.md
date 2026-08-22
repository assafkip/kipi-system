---
id: crpr-bus-verifier-can-fail
title: Make the canonical-digest check reachable, substantive, and error-proof
status: open
priority: p0
parent_prd: prd-canonical-read-path-repair-2026-08-22
allowed_files:
  - plugins/kipi-core/kipi-mcp/src/kipi_mcp/bus_verifier.py
  - plugins/kipi-core/kipi-mcp/tests/test_bus_verifier.py
disallowed_files:
  - plugins/kipi-core/kipi-mcp/src/kipi_mcp/paths.py
  - .claude/**
  - .prd-os/**
required_checks:
  - python3 -m pytest -q plugins/kipi-core/kipi-mcp/tests/test_bus_verifier.py
required_reviews:
  - runtime-owner
bypass_check: "python3 -m pytest -q plugins/kipi-core/kipi-mcp/tests/test_bus_verifier.py -k 'reachable or substantive or error_key'"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-canonical-read-path-repair-2026-08-22 finding=finding-13 at=2026-08-22T20:07:44Z -->

# Make the canonical-digest check reachable, substantive, and error-proof

## Context

Parent PRD: `.prd-os/prds/prd-canonical-read-path-repair-2026-08-22.md`

## Acceptance

THREE independent defects, THREE independent tests, each shown RED first and each killed by its own mutation. (1) REACHABLE: canonical-digest.json is in phase 1 required; reverting only this must turn a test red. (2) SUBSTANTIVE: the exact empty digest captured 2026-08-22 must be rejected - talk_tracks {}, objections [], current_state {}, discovery {}, decisions [], warnings 5 not-found messages, valid false; reverting only the lambda must turn a DIFFERENT test red. (3) ERROR SHORT-CIRCUIT (finding-13): bus_verifier.py:46-52 tests 'error' in data BEFORE the structure check and emits warn WITHOUT setting all_pass=False, so a required canonical-digest.json of exactly {"error":"canonical digest unavailable"} yields pass:true even after (1) and (2). Assert verify() returns pass False for that input. A required-file failure is a hard fail per bus_verifier.py:42-81, so assert on pass, never on the presence of a warn. SEQUENCING (finding-27): making this file required while canonical_dir still resolves to ~/.kipi-system/instances/<name>/canonical turns every phase-1 run red on 23 instances. Add a precondition test asserting canonical_dir does NOT resolve under the plugin-data base; it fails until srsa lands, which is the intended block.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Make the canonical-digest check reachable, substantive, and error-proof
