---
id: lr-trigger-inventory
title: trigger-inventory.py derives stages from the tree, diffs them against registered triggers, and prints its excluded scope
status: open
priority: p0
parent_prd: prd-lessons-rail-and-up-rail-2026-09-02
allowed_files:
  - q-system/.q-system/scripts/trigger-inventory.py
  - q-system/.q-system/stages-exempt.json
  - q-system/.q-system/tests/test_trigger_inventory.py
  - q-system/.q-system/capability/expected_tests/q-system__.q-system__tests__test_trigger_inventory.py.json
disallowed_files:
  - .claude/**
  - plugins/prd-os/**
  - .prd-os/**
  - q-consult/**
required_checks:
  - python3 -m pytest -q q-system/.q-system/tests/test_trigger_inventory.py
required_reviews: []
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/test_trigger_inventory.py -k 'known_dead or worktree_copy or unregistered'"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-lessons-rail-and-up-rail-2026-09-02 finding=finding-6 at=2026-09-02T00:25:35Z -->

# trigger-inventory.py derives stages from the tree, diffs them against registered triggers, and prints its excluded scope

## Context

Parent PRD: `.prd-os/prds/prd-lessons-rail-and-up-rail-2026-09-02.md`

## Acceptance

RED first against a tmp repo fixture: candidates are every *.py and *.sh under q-system/.q-system/scripts/ plus repo-root *.sh, never a hand list; triggers come from plist templates, an installed-plists directory the test provides, settings.json hooks, plugin hooks.json and workflow files, closed transitively over scripts named inside triggered scripts; stages-exempt.json entries need a reason and an existing file (a stale exemption exits 2); a brand-new script dropped into the fixture with no trigger is surfaced without any registration; the diff and the excluded-scope counts (.claude/worktrees/, .wt-*) are printed; run on this repo with the installed-plists dir empty it surfaces the three known dead stages (the test plants the pre-fix state for route-overrides-to-learn.py); a fake dead stage planted inside a worktree copy is NOT counted. Live run on this repo recorded at closeout.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] trigger-inventory.py derives stages from the tree, diffs them against registered triggers, and prints its excluded scope
