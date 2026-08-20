---
id: needs-scope-redrive
title: Piece A: linear-dor-drafter consumes needs-scope, so the promise the worker already prints becomes true
status: closed
priority: p0
parent_prd: prd-terminal-state-redrive-2026-08-01
allowed_files:
  - q-system/.q-system/scripts/linear-dor-drafter.py
  - q-system/.q-system/scripts/test/test-linear-dor-drafter*.sh
  - q-system/.q-system/scripts/test/test_linear_dor_drafter*.py
disallowed_files: []
required_checks:
  - bash q-system/.q-system/scripts/test/test-linear-dor-drafter-redrive.sh
required_reviews: []
bypass_check: "A fixture issue carrying BOTH a '## Definition of Ready' heading AND the needs-scope label is SELECTED by the drafter's selection predicate. This is the exact case needs_dor() excluded, so a green here means the exclusion is gone rather than renamed."
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-terminal-state-redrive-2026-08-01 finding=finding-1 at=2026-08-01T19:41:22Z -->

# Piece A: linear-dor-drafter consumes needs-scope, so the promise the worker already prints becomes true

## Context

Parent PRD: `.prd-os/prds/prd-terminal-state-redrive-2026-08-01.md`

## Acceptance

Observed RED first against current needs_dor(), which returns False for any description containing 'Definition of Ready'. Drafter fetches labels (it queries none today). A needs-scope issue is redrafted, not skipped, and the label is removed on success so the picker offers it again. Redraft attempts are capped per issue and the cap's exhaustion is recorded as an honest terminal with a rationale, never a new tier. PREREQUISITE (finding-13): determine why the drafter never reached ASK-274 and pin the answer with a test; the unsorted todo[:limit] batch at linear-dor-drafter.py:508-525 is the live starvation candidate and this issue changes that same selection path. Touches no worker code, so it cannot collide with in-flight ASK-281.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] Piece A: linear-dor-drafter consumes needs-scope, so the promise the worker already prints becomes true
