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
  - bash -c 'cd plugins/kipi-core/kipi-mcp && PYTHONPATH=src python3 -m pytest -q tests/test_bus_verifier.py'
required_reviews:
  - runtime-owner
bypass_check: "bash -c 'cd plugins/kipi-core/kipi-mcp && PYTHONPATH=src python3 -m pytest -q tests/test_bus_verifier.py -k \"reachable or substantive or error_key or sequencing\"'"
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
- [x] Make the canonical-digest check reachable, substantive, and error-proof

## Evidence

The required_check as originally written COULD NOT RUN. From repo root the bare
pytest invocation exits 4 on a conftest ImportError (`No module named 'kipi_mcp'`).
Same defect class as finding-2 / finding-24. Corrected above and re-measured:

    bare   invocation -> rc=4 (conftest ImportError, zero tests collected)
    scoped invocation -> rc=0, 17 passed

Three defects, three tests, all green; plus the sequencing predicate with BOTH
branches asserted.

THE SUITE PINNED DEFECT 3. `test_phase1_calendar_with_error_key` was GREEN while
asserting the buggy behaviour (`warn` on a required file carrying an error key).
That green test is why the defect survived. It is inverted to assert the verdict
(`pass is False`), which is part of the fix, not collateral damage.

SUBSTANCE CHECK CALIBRATED AGAINST REAL DATA, not intuition: the live tree yields
decisions=10, objections=5, warnings=0 and all-empty talk_tracks, so requiring
talk_tracks would have redded every run against real data. The predicate passes the
live shape and rejects both the captured all-empty digest and Codex finding-14's
nonempty placeholder.
