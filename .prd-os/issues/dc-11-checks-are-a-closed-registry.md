---
id: dc-11-checks-are-a-closed-registry
title: Outside checks run from a closed registry in the gate, and the tripwire says when it skipped
status: in-progress
priority: p1
parent_prd: prd-design-chain-seal-reads-verdicts-2026-09-18
allowed_files:
  - plugins/kipi-design/.claude-plugin/plugin.json
  - plugins/kipi-design/hooks/dogfood_gate.py
  - plugins/kipi-design/hooks/test_dogfood_gate.py
  - plugins/kipi-design/hooks/test_dogfood_check_cli.py
  - q-system/.q-system/capability/expected_tests/*
  - q-system/.q-system/scripts/design-chain-gate.py
  - q-system/.q-system/scripts/test/test_dc_check_registry.py
disallowed_files: []
required_checks:
  - python3 q-system/.q-system/scripts/test/test_dc_check_registry.py
  - python3 plugins/kipi-design/hooks/test_dogfood_check_cli.py
required_reviews: []
bypass_check: "python3 q-system/.q-system/scripts/test/test_dc_check_registry.py"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-design-chain-seal-reads-verdicts-2026-09-18 finding=finding-9 at=2026-09-18T20:21:26Z -->

# Outside checks run from a closed registry in the gate, and the tripwire says when it skipped

## Context

Parent PRD: `.prd-os/prds/prd-design-chain-seal-reads-verdicts-2026-09-18.md`

## Acceptance

design-chain.json lists check NAMES with path arguments; commands and pass criteria live in the gate. An unknown name is refused. seal runs each and reads the exit code; checks/ being non-empty no longer counts. dogfood_gate.py gains a distinguishable result for 'skipped as internal' (ASK-1746) that the registry treats as not run.


The RED FIRST test is A-checks: round A with every reader STAY and tripwire FAIL, bio_gate BLOCKED; it seals before this change and refuses after, naming the checks. (Sana, 2026-09-19, moved from dc-21.)

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] Outside checks run from a closed registry in the gate, and the tripwire says when it skipped
