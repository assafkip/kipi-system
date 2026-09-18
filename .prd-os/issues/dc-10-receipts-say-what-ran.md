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

seal writes a stages list per page (floor, vision, craft, gap, impeccable, readers, checks, engines) with each producer's output sha. sealed_and_unedited() accepts a receipt with a stages record, or one whose receipts.json has a git commit dated before the coded cutover; status and the hook block message print the stages. Negative control: RCA round B (hand-typed receipt, uncommitted) reads OPEN. Population check: every sealed round committed before the cutover still reads COMPLETE. ADDED 2026-09-18 by Sana's decision on dc-02's adversarial finding-6 (a gate copy beside stand-ins seals a real round and its receipt is indistinguishable): Each stage record names the producer's repo-relative path and the sha256 of the file that ran; a stage is honored only when that sha matches the file at that path now or appears in git history for that path, so stand-ins run from a copied directory are refused, and a test proves a gate or producer upgrade leaves every previously sealed round COMPLETE. ADDED 2026-09-18 by Sana's disposition of dc-02 finding-11 (the no-override test is a review aid, evaded two rounds running): The stage record also names the gate file's own repo-relative path and the sha256 of the file that ran, honored under the same rule (matches the file at that path now, or appears in git history for that path), so a modified or copied gate is refused like a copied producer. ADDED 2026-09-18 by Sana's decision on dc-03 finding-10 (served-bytes proof covered the HTML only, so a swapped shared.css left every sha matching while an honest re-measure FAILED): `sealed_and_unedited()` also recomputes the round's asset digest recorded by seal and refuses the round when it differs, and a test proves a subresource swap after seal flips the round from COMPLETE to OPEN. ADDED 2026-09-18 by Sana's disposition of ASK-1808 adversarial finding-7: the digest `sealed_and_unedited()` recomputes excludes only the files a seal itself writes (`standard.json`, `checks/gap.json`, `receipts.json`), not the chain records, so an edit to `brief.md`, `craft-manifest.json`, `directions.md`, `critique.md`, `proof.md`, `sources.json` or `gate/reader-runs.jsonl` after the seal also flips the round from COMPLETE to OPEN; a test proves one of each. ORDER, same decision: dc-10 now runs BEFORE dc-21 (ASK-1808 -> ASK-1806 -> dc-10 -> dc-21), because it closes a live bypass and dc-21 is test debt.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Receipts record the stages that ran, and the passive gate honors a bare receipt only when git shows it predates the cutover
