---
id: dc-25-rollout-proof
title: A script proves the fleet load path end to end
status: closed
priority: p2
parent_prd: prd-design-chain-seal-reads-verdicts-2026-09-18
allowed_files:
  - .github/workflows/validate.yml
  - q-system/.q-system/capability/expected_tests/*
  - q-system/.q-system/scripts/design-chain-rollout-proof.sh
disallowed_files: []
required_checks:
  - bash q-system/.q-system/scripts/design-chain-rollout-proof.sh --selftest
required_reviews: []
bypass_check: "bash q-system/.q-system/scripts/design-chain-rollout-proof.sh --selftest"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-design-chain-seal-reads-verdicts-2026-09-18 finding=finding-30 at=2026-09-18T20:21:26Z -->

# A script proves the fleet load path end to end

## Context

Parent PRD: `.prd-os/prds/prd-design-chain-seal-reads-verdicts-2026-09-18.md`

## Acceptance

CI runs the design-chain tests for real, or it does not claim to (ASK-1841 adversarial review, CONFIRMED by reading, 2026-09-19): `.github/workflows/validate.yml` installs no playwright or chromium and does not set DC_REQUIRE_REAL_PRODUCERS, so every test built on test_dc_seal_snapshot.Base calls skipTest, the file exits 0, and the capability gate reports green. test_9 sat red since dc-05 this way. Add a step before the capability-gate step (validate.yml ~line 51): `pip install playwright && python -m playwright install --with-deps chromium`, and `DC_REQUIRE_REAL_PRODUCERS: "1"` to that step's env (~line 54). Test: a design-chain test file run in CI without a browser FAILS, it does not skip. Amend allowed_files for `.github/workflows/validate.yml` at issue-start.

The script checks: the marketplace clone holds the command; an instance root passed as an argument holds all design scripts and the hook entries; the gate hook run with CLAUDE_PROJECT_DIR set to that instance exits 2 on an unsealed page. --selftest runs it against a temp instance. The founder runs the fleet sync; this script is run against consulting afterwards and its output is pasted in the closeout.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] A script proves the fleet load path end to end

## Amendments

### 2026-09-19T22:32:53Z
Reason: dc-25 acceptance names .github/workflows/validate.yml (the playwright install and DC_REQUIRE_REAL_PRODUCERS=1 before the capability-gate step); the spec says to amend allowed_files for it at issue-start

Before:
- allowed_files: ['.github/workflows/validate.yml', 'q-system/.q-system/capability/expected_tests/*', 'q-system/.q-system/scripts/design-chain-rollout-proof.sh']
- required_checks: ['bash q-system/.q-system/scripts/design-chain-rollout-proof.sh --selftest']
- disallowed_files: []

After:
- allowed_files: ['.github/workflows/validate.yml', 'q-system/.q-system/capability/expected_tests/*', 'q-system/.q-system/scripts/design-chain-rollout-proof.sh']
- required_checks: ['bash q-system/.q-system/scripts/design-chain-rollout-proof.sh --selftest']
- disallowed_files: []
