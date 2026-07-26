---
id: issue-updater-one-model-scan-2026-07-26
title: One scan, two projections, for what the disposable copy contains
status: closed
priority: p1
parent_prd: prd-updater-consolidation-2026-07-26
allowed_files:
  - kipi-update.sh
  - q-system/.q-system/scripts/test/test-kipi-update-safety.sh
disallowed_files: []
required_checks:
  - bash q-system/.q-system/scripts/test/test-kipi-update-safety.sh
  - bash q-system/.q-system/scripts/test/test-kipi-update-dry-final-state.sh
  - bash -c 'o=$(python3 -m pytest -q --ignore=scripts --ignore=.claude --ignore=plugins/kipi-core/kipi-mcp --ignore=plugins/kipi-design 2>&1); printf "%s\n" "$o" | tail -1; printf "%s\n" "$o" | grep -Eq "^3 failed, 357 passed, 1 skipped" && [ "$(printf "%s\n" "$o" | grep -c "^FAILED plugins/prd-os/tests/test_propagation.py::test_rsync_block_excludes_protected_path")" -eq 3 ]'
required_reviews: []
bypass_check: "test \"$(grep -c -- '-name .git -print' kipi-update.sh)\" -eq 1 && test \"$(grep -c 'MODEL_EXCLUDES=(' kipi-update.sh)\" -eq 1 && ! grep -q 'NESTED_SKIPPED\\|NESTED_COUNT' kipi-update.sh"
---
<!-- generated-by: prd_split.py prd=prd-updater-consolidation-2026-07-26 finding=finding-1 at=2026-07-26T05:57:44Z -->

# One scan, two projections, for what the disposable copy contains

## Context

Parent PRD: `.prd-os/prds/prd-updater-consolidation-2026-07-26.md`

## Acceptance

Runs SECOND. model_skip_scan is the single cached scan; model_rsync_excludes and model_walk_skips are two named projections of it, neither derived from the other; .git is in the rsync projection and NOT in the walk projection, with the asymmetry's reason in a comment; a new fixture plants a dangling symlink under the instance's own .git/ and asserts the run still refuses, pinning today's behaviour rather than introducing new behaviour; the submodule carve-out is preserved verbatim; baseline unchanged.

## Amendments

### 2026-07-26T06:29:51Z
Reason: bypass_check counted calls to model_skip_scan (>=3), which forced a redundant direct call at the loop site purely to satisfy the number. Adversarial review correctly flagged that call as dead: model_rsync_excludes re-enters the scan itself, so nothing between the two lines reads MODEL_SKIPPED_PATHS. Removed the dead call and replaced the proxy with a check of the actual invariant: exactly one nested-repo scan in the file, MODEL_EXCLUDES assigned in exactly one place, and no surviving NESTED_SKIPPED/NESTED_COUNT. allowed_files and required_checks unchanged; no change to the work.

Before:
- allowed_files: ['kipi-update.sh', 'q-system/.q-system/scripts/test/test-kipi-update-safety.sh']
- required_checks: ['bash q-system/.q-system/scripts/test/test-kipi-update-safety.sh', 'bash q-system/.q-system/scripts/test/test-kipi-update-dry-final-state.sh', 'bash -c \'o=$(python3 -m pytest -q --ignore=scripts --ignore=.claude --ignore=plugins/kipi-core/kipi-mcp --ignore=plugins/kipi-design 2>&1); printf "%s\\n" "$o" | tail -1; printf "%s\\n" "$o" | grep -Eq "^3 failed, 357 passed, 1 skipped" && [ "$(printf "%s\\n" "$o" | grep -c "^FAILED plugins/prd-os/tests/test_propagation.py::test_rsync_block_excludes_protected_path")" -eq 3 ]\'']
- disallowed_files: []

After:
- allowed_files: ['kipi-update.sh', 'q-system/.q-system/scripts/test/test-kipi-update-safety.sh']
- required_checks: ['bash q-system/.q-system/scripts/test/test-kipi-update-safety.sh', 'bash q-system/.q-system/scripts/test/test-kipi-update-dry-final-state.sh', 'bash -c \'o=$(python3 -m pytest -q --ignore=scripts --ignore=.claude --ignore=plugins/kipi-core/kipi-mcp --ignore=plugins/kipi-design 2>&1); printf "%s\\n" "$o" | tail -1; printf "%s\\n" "$o" | grep -Eq "^3 failed, 357 passed, 1 skipped" && [ "$(printf "%s\\n" "$o" | grep -c "^FAILED plugins/prd-os/tests/test_propagation.py::test_rsync_block_excludes_protected_path")" -eq 3 ]\'']
- disallowed_files: []
