---
id: dc-03-seal-owns-the-served-round
title: seal serves the round on an ephemeral port and producers prove they measured the local bytes
status: open
priority: p1
parent_prd: prd-design-chain-seal-reads-verdicts-2026-09-18
allowed_files:
  - q-system/.q-system/capability/expected_tests/*
  - q-system/.q-system/scripts/design-chain-gate.py
  - q-system/.q-system/scripts/design-gap-check.py
  - q-system/.q-system/scripts/design-standard-check.py
  - q-system/.q-system/scripts/test/test_dc_served_round.py
disallowed_files: []
required_checks:
  - python3 q-system/.q-system/scripts/test/test_dc_served_round.py
required_reviews: []
bypass_check: "python3 q-system/.q-system/scripts/test/test_dc_served_round.py"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-design-chain-seal-reads-verdicts-2026-09-18 finding=finding-3 at=2026-09-18T20:21:26Z -->

# seal serves the round on an ephemeral port and producers prove they measured the local bytes

## Context

Parent PRD: `.prd-os/prds/prd-design-chain-seal-reads-verdicts-2026-09-18.md`

## Acceptance

seal binds port 0, passes the URL to every producer, and stops the server in a finally. Producers compare the sha of the served bytes with the local file and exit 2 on a mismatch. Test: a decoy server serving different bytes cannot produce a pass. No literal port remains in the gate or the producers. ADDED 2026-09-18 by Sana's decision on dc-02's adversarial finding-8: design-gap-check.py exits 3 for could-not-measure and keeps 2 for below-the-exemplar-floor; seal labels each code distinctly, with a test per code. ADDED 2026-09-18 by Sana's disposition of dc-02 findings 12 and 13: The producer child also runs with -s: -E ignores PYTHONUSERBASE but leaves the default user site enabled, so usercustomize.py there is imported at startup. Test: a usercustomize.py in the child's user site cannot alter a verdict. Refusal names -s when a producer dies with ModuleNotFoundError. Before running a producer, seal removes that page's standard.json entry (and checks/gap.json before the gap producer), so an entry exists afterwards only if this run wrote it; mtime is then a cross-check, not the mechanism.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] seal serves the round on an ephemeral port and producers prove they measured the local bytes
