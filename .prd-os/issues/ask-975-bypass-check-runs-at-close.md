---
id: ask-975-bypass-check-runs-at-close
title: bypass_check runs at close before it is registered (sp-50db1764)
status: closed
priority: p0
allowed_files:
  - plugins/kipi-dsse/scripts/issue_runner.py
  - plugins/kipi-dsse/scripts/test_bypass_check_runs_at_close.py
  - plugins/kipi-dsse/.claude-plugin/plugin.json
disallowed_files: []
required_checks:
  - python3 plugins/kipi-dsse/scripts/test_bypass_check_runs_at_close.py
  - bash -c 'cd plugins/kipi-core/kipi-mcp && PYTHONPATH=src python3 -m pytest -q tests/test_paths.py'
required_reviews: []
deliverables_count: 2
---
<!-- generated-by: prd_split.py prd=prd-manual finding=sp-50db1764 at=2026-08-23T02:10:00Z -->

# bypass_check runs at close before it is registered

## Context

`_enforce_spine_contract` called `prd_runner.gate_register(...,
command=bypass_check)` at close WITHOUT executing the command. Every issue
closed through that path appended a standing gate that never ran, into a
registry that only grows and has no hand-clear (sp-50db1764, blocker). A green
that was never executed is not evidence of anything; this contaminated the
closure record of prior work.

Fix at the chokepoint (one writer to the close path), not N per-spec
corrections: `_enforce_spine_contract` now runs the bypass_check first and
refuses close on any nonzero rc, with rc=5 (pytest collected nothing) named
distinctly from rc=1, because a zero-selection gate can never go green.

## Evidence

RED before the fix, measured against `origin/main`'s issue_runner.py in an
isolated temp copy (2026-08-23):

```
AssertionError: close succeeded while its bypass_check exited 3 — a gate was
registered for a command that never ran green
{"closed": "bypass-red", ...}
```

The mutation IS the guard removal: main's code has no run step, and the test
catches exactly that.

GREEN after the fix on this branch:

```
$ python3 plugins/kipi-dsse/scripts/test_bypass_check_runs_at_close.py
bypass-check-runs-at-close tests: PASS
```

Three cases: refusal on failing bypass_check with NOTHING appended to
gates.jsonl and the spec left open; rc=5 named distinctly; registration only
after a green run, with the recorded command matching the spec.

Plugin version bumped kipi-dsse 0.14.1 -> 0.14.2 so deployed clones can tell
the copies apart.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] `_enforce_spine_contract` runs the bypass_check and refuses close on nonzero (rc=5 named as collected-nothing), registering nothing on refusal
- [x] Reproducer-first test file covering red-refusal, rc=5 naming, and register-only-after-green
