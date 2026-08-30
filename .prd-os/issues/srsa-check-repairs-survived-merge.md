---
id: srsa-check-repairs-survived-merge
title: Prove the srsa check repairs survived the squash-merge with collection evidence
status: closed
priority: p0
allowed_files: []
disallowed_files: []
required_checks:
  - bash -c 'cd plugins/kipi-core/kipi-mcp && PYTHONPATH=src python3 -m pytest -q tests/test_paths.py'
  - bash -c 'cd plugins/kipi-core/kipi-mcp && PYTHONPATH=src python3 -m pytest -q tests/test_paths.py --collect-only'
required_reviews: []
bypass_check: "PYTHONPATH=plugins/kipi-core/kipi-mcp/src python3 -m pytest -q plugins/kipi-core/kipi-mcp/tests/test_paths.py -k 'fails_closed or resolves_instance_domain_dir'"
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-manual finding=finding-manual at=2026-08-23T01:20:00Z -->

# Prove the srsa check repairs survived the squash-merge

## Context

Verification-only issue (no source edits). sp-0cf100b3 and sp-b82fda60 were
filed 2026-08-22 against a broken state of
`plugins/kipi-core/kipi-mcp/tests/test_paths.py`: four tests requested fixture
`registry_fixture`, defined nowhere, so the file ERRORED AT COLLECTION and the
srsa required-check passed by not running; and the spec's bypass_check
`-k 'ambiguous or plugin_cache_write'` matched NO test (rc=5). Both were
repaired pre-merge in commit 63248474 and shipped inside squashed PR #240
(de2e4624). A squash-merge erases per-commit provenance, so "it was fixed in a
commit that no longer exists" is not evidence. This issue re-measures the
REPO TREE as it exists after the merge.

## Acceptance

Measured 2026-08-23 on branch sana/ask-975-bypass-check-runs-at-close
(= origin/main + ASK-975 fix), quoted from the runs:

- [x] COLLECTION REPAIRED (sp-0cf100b3):
      `PYTHONPATH=plugins/kipi-core/kipi-mcp/src python3 -m pytest -q
      plugins/kipi-core/kipi-mcp/tests/test_paths.py --collect-only`
      collected **21 tests** (was: ImportError/collection error at the four
      `registry_fixture` lines). No test requests `registry_fixture`; conftest
      ships `tmp_registry`, `tmp_registry_with_instances`,
      `registry_with_domain_dir`.
- [x] FULL FILE GREEN (sp-0cf100b3): the same path without `--collect-only`
      passes 21/21 — the required-check now RUNS and PASSES instead of passing
      by not running.
- [x] BYPASS_CHECK COLLECTS REAL TESTS AND IS GREEN (sp-b82fda60): the spec
      selector `-k 'fails_closed or resolves_instance_domain_dir'`
      collects **3** cases (`test_duplicate_registry_paths_fail_closed`,
      `test_unregistered_repo_fails_closed`,
      `test_canonical_dir_resolves_instance_domain_dir`) and exits 0. The
      concrete input that made the OLD selector red for the right reason was
      any run at all — it matched nothing; this selector would go red if any
      of its three cases regressed, which is the property that makes it a
      check rather than decoration.
- [x] The close-time chokepoint that let both defects hide (bypass_check
      registered but never executed) is separately fixed under ASK-975 /
      sp-50db1764; this issue's bypass_check therefore RAN at close before
      being registered.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] Re-measure collection count, full-file result, and bypass_check selector against the post-merge tree and record the numbers here
