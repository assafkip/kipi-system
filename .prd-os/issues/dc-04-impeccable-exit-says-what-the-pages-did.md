---
id: dc-04-impeccable-exit-says-what-the-pages-did
title: design-impeccable-check.py fails when a page raises an anti-pattern
status: closed
priority: p1
parent_prd: prd-design-chain-seal-reads-verdicts-2026-09-18
allowed_files:
  - q-system/.q-system/capability/expected_tests/*
  - q-system/.q-system/scripts/design-chain-gate.py
  - q-system/.q-system/scripts/design-impeccable-check.py
  - q-system/.q-system/scripts/test/test_dc_impeccable_exit.py
  - q-system/.q-system/scripts/test/stub_producers/design-impeccable-check.py
  - q-system/.q-system/scripts/test_design_chain_gate.py
disallowed_files: []
required_checks:
  - DC_REQUIRE_REAL_PRODUCERS=1 python3 q-system/.q-system/scripts/test/test_dc_impeccable_exit.py
  - python3 q-system/.q-system/scripts/test_design_chain_gate.py
required_reviews: []
bypass_check: "python3 q-system/.q-system/scripts/test/test_dc_impeccable_exit.py"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-design-chain-seal-reads-verdicts-2026-09-18 finding=finding-4 at=2026-09-18T20:21:26Z -->

# design-impeccable-check.py fails when a page raises an anti-pattern

## Context

Parent PRD: `.prd-os/prds/prd-design-chain-seal-reads-verdicts-2026-09-18.md`

## Acceptance

Exit contract: 0 control fired and pages clean; 1 control did not fire; 2 could not run; 3 at least one page flagged. The value computed at worst = max(worst, rc) is consumed. seal refuses on 1, 2 and 3. Test drives the script with a stub detector. ADDED 2026-09-18 by Sana's decision on dc-03 finding-4: `design-impeccable-check.py` has no default `--url-base`; seal hands it the served round, and it exits 2 when served bytes differ from the local file. seal RUNS the impeccable producer when `require_impeccable` is set (the same shape as the gap producer: the round's prior checks/impeccable.txt removed first, only this run may write it), handing it the served round. The producer serves its own negative control on a private loopback port so the control goes through the same browser engine as the pages. The gate-copy suite gets a stand-in producer beside the other two.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] design-impeccable-check.py fails when a page raises an anti-pattern (DELIVERED: exit 0 clean / 1 dead control / 2 could not run / 3 flagged; control judged by the detector's exit; no default --url-base; served bytes checked; control served on its own port; seal runs the producer with every page it seals and refuses on 1, 2, 3; detector from an empty cwd with --no-config. Moved: webdriver cloaking to ASK-1835.)

## Amendments

### 2026-09-19T06:43:54Z
Reason: Scope (Sana's standing rule: amends for tests a change legitimately breaks): seal now runs the impeccable producer, so the gate-copy suite needs a stand-in beside the other two and its require_impeccable tests change shape; required check gains DC_REQUIRE_REAL_PRODUCERS=1 (the seal tests use the real detector) and the gate suite.

Before:
- allowed_files: ['q-system/.q-system/capability/expected_tests/*', 'q-system/.q-system/scripts/design-chain-gate.py', 'q-system/.q-system/scripts/design-impeccable-check.py', 'q-system/.q-system/scripts/test/test_dc_impeccable_exit.py']
- required_checks: ['python3 q-system/.q-system/scripts/test/test_dc_impeccable_exit.py']
- disallowed_files: []

After:
- allowed_files: ['q-system/.q-system/capability/expected_tests/*', 'q-system/.q-system/scripts/design-chain-gate.py', 'q-system/.q-system/scripts/design-impeccable-check.py', 'q-system/.q-system/scripts/test/test_dc_impeccable_exit.py', 'q-system/.q-system/scripts/test/stub_producers/design-impeccable-check.py', 'q-system/.q-system/scripts/test_design_chain_gate.py']
- required_checks: ['DC_REQUIRE_REAL_PRODUCERS=1 python3 q-system/.q-system/scripts/test/test_dc_impeccable_exit.py', 'python3 q-system/.q-system/scripts/test_design_chain_gate.py']
- disallowed_files: []
