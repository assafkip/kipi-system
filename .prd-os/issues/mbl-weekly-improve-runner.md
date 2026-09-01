---
id: mbl-weekly-improve-runner
title: Weekly runner triggers producer, learner and pass in order; plist template; empty is not a proposal
status: closed
priority: p1
parent_prd: prd-morning-brief-learns-2026-09-01
allowed_files:
  - q-system/.q-system/scripts/weekly-improve.sh
  - q-system/.q-system/scripts/com.kipi.weekly-improve.plist
  - q-system/.q-system/scripts/route-overrides-to-learn.py
  - q-system/.q-system/tests/test_route_overrides_to_learn.py
  - q-system/.q-system/capability/expected_tests/q-system__.q-system__tests__test_route_overrides_to_learn.py.json
disallowed_files:
  - .claude/**
  - plugins/prd-os/**
  - .prd-os/**
  - q-consult/**
  - q-system/.q-system/data/metrics.db
  - q-system/.q-system/scripts/install-plist.sh
required_checks:
  - python3 -m pytest -q q-system/.q-system/tests/test_route_overrides_to_learn.py
required_reviews: []
bypass_check: "python3 -m pytest -q q-system/.q-system/tests/test_route_overrides_to_learn.py -k 'empty_is_not_a_proposal or order'"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-morning-brief-learns-2026-09-01 finding=finding-9 at=2026-09-01T22:00:59Z -->

# Weekly runner triggers producer, learner and pass in order; plist template; empty is not a proposal

## Context

Parent PRD: `.prd-os/prds/prd-morning-brief-learns-2026-09-01.md`

## Acceptance

weekly-improve.sh runs draft-vs-sent.py, then route-overrides-to-learn.py, then weekly-improve.py, in that order, logging each step's exit code to q-system/output/weekly-improve.log (the self-healing-retry contract: every attempt logged); a failing producer does not skip the pass. The plist template runs that script Monday 06:30 with __KIPI_REPO__/__HOME__/__USER__ and no /Users/ literal (install-plist.sh already resolves templates by label, finding-10). RED first: (1) route-overrides-to-learn.py over an empty copy_edits exits 2 and writes an empty-body file, and a checker in the runner reports that file as EMPTY so a dated file alone never counts as a proposal; (2) the runner's order is asserted from a dry-run trace; (3) plist template placeholders asserted. Live proof at closeout: install-plist.sh weekly-improve, launchctl kickstart from a bare environment, one log line per step.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] Weekly runner triggers producer, learner and pass in order; plist template; empty is not a proposal (weekly-improve.sh finds the learner's output by mtime, moves an empty file to _inbox/.empty/ so the pass cannot list it; com.kipi.weekly-improve.plist Monday 06:30; learner gains tmp-path env overrides and its first test; 9 tests red-first incl. a bare-environment run (PATH=/usr/bin:/bin, temp HOME); mutation proof in the closing commit; 3 Codex findings accepted and patched. LIVE launchd install DEFERRED to landing: this branch lives in a worktree, and install-plist.sh renders __KIPI_REPO__ to the worktree path, so a job installed today would point at a checkout that disappears after merge, the exact silent-death class this PRD hunts. `install-plist.sh weekly-improve` + `launchctl kickstart gui/$UID/com.kipi.weekly-improve` run from the main checkout once Sana lands the branch)
