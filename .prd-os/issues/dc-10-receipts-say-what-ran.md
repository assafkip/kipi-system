---
id: dc-10-receipts-say-what-ran
title: Receipts record the stages that ran, and the passive gate honors a bare receipt only when git shows it predates the cutover
status: open
priority: p1
parent_prd: prd-design-chain-seal-reads-verdicts-2026-09-18
allowed_files:
  - q-system/.q-system/capability/expected_tests/*
  - q-system/.q-system/scripts/design-chain-gate.py
  - q-system/.q-system/scripts/test/test_dc_receipts.py
disallowed_files: []
required_checks:
  - python3 q-system/.q-system/scripts/test/test_dc_receipts.py
required_reviews: []
bypass_check: "python3 q-system/.q-system/scripts/test/test_dc_receipts.py"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-design-chain-seal-reads-verdicts-2026-09-18 finding=finding-1 at=2026-09-18T20:21:26Z -->

# Receipts record the stages that ran, and the passive gate honors a bare receipt only when git shows it predates the cutover

## Context

Parent PRD: `.prd-os/prds/prd-design-chain-seal-reads-verdicts-2026-09-18.md`

## Acceptance

seal writes a stages list per page (floor, vision, craft, gap, impeccable, readers, checks, engines) with each producer's output sha. sealed_and_unedited() accepts a receipt with a stages record, or one whose receipts.json has a git commit dated before the coded cutover; status and the hook block message print the stages. Negative control: RCA round B (hand-typed receipt, uncommitted) reads OPEN. Population check: every sealed round committed before the cutover still reads COMPLETE. ADDED 2026-09-18 by Sana's decision on dc-02's adversarial finding-6 (a gate copy beside stand-ins seals a real round and its receipt is indistinguishable): Each stage record names the producer's repo-relative path and the sha256 of the file that ran; a stage is honored only when that sha matches the file at that path now or appears in git history for that path, so stand-ins run from a copied directory are refused, and a test proves a gate or producer upgrade leaves every previously sealed round COMPLETE.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Receipts record the stages that ran, and the passive gate honors a bare receipt only when git shows it predates the cutover
