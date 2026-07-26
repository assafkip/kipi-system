---
id: issue-updater-one-plugin-answer-2026-07-26
title: One answer to what is a plugin
status: closed
priority: p1
parent_prd: prd-updater-consolidation-2026-07-26
allowed_files:
  - kipi-update.sh
disallowed_files: []
required_checks:
  - bash q-system/.q-system/scripts/test/test-kipi-update-safety.sh
  - bash q-system/.q-system/scripts/test/test-kipi-update-build-artifacts.sh
  - bash -c 'o=$(python3 -m pytest -q --ignore=scripts --ignore=.claude --ignore=plugins/kipi-core/kipi-mcp --ignore=plugins/kipi-design 2>&1); printf "%s\n" "$o" | tail -1; printf "%s\n" "$o" | grep -Eq "^3 failed, 357 passed, 1 skipped" && [ "$(printf "%s\n" "$o" | grep -c "^FAILED plugins/prd-os/tests/test_propagation.py::test_rsync_block_excludes_protected_path")" -eq 3 ]'
required_reviews: []
bypass_check: "test \"$(grep -c 'SCRIPT_DIR/plugins' kipi-update.sh)\" -eq 1"
---
<!-- generated-by: prd_split.py prd=prd-updater-consolidation-2026-07-26 finding=finding-7 at=2026-07-26T05:57:44Z -->

# One answer to what is a plugin

## Context

Parent PRD: `.prd-os/prds/prd-updater-consolidation-2026-07-26.md`

## Acceptance

Runs FIRST. SKELETON_PLUGIN_ROOT defined once; managed_plugin_names and is_managed_plugin_path are the only deciders; the staging enumeration is re-rooted per managed plugin and :301's [ -d ] guard is deleted; the three behaviour-identity cases (loose file under plugins/, dangling top-level symlink, symlink-to-real-directory) are each demonstrated unchanged before and after; no test added; baseline unchanged.

## Amendments

### 2026-07-26T06:05:24Z
Reason: required_checks encoded the pytest baseline as 'exit 0', which is unsatisfiable: the 3 pre-existing test_propagation failures the PRD forbids fixing make bare pytest always exit 1, so no issue in this PRD could ever verify. Replaced with a command asserting the PRD's already-approved DONE text verbatim ('still exactly the same 3 pre-existing failures, 357 passed') and additionally pinning the IDENTITY of the 3. Strictly stronger than the original intent. allowed_files unchanged; no change to the work. Applied to all 5 specs and the PRD manifest.

Before:
- allowed_files: ['kipi-update.sh']
- required_checks: ['bash q-system/.q-system/scripts/test/test-kipi-update-safety.sh', 'bash q-system/.q-system/scripts/test/test-kipi-update-build-artifacts.sh', 'python3 -m pytest -q --ignore=scripts --ignore=.claude --ignore=plugins/kipi-core/kipi-mcp --ignore=plugins/kipi-design']
- disallowed_files: []

After:
- allowed_files: ['kipi-update.sh']
- required_checks: ['bash q-system/.q-system/scripts/test/test-kipi-update-safety.sh', 'bash q-system/.q-system/scripts/test/test-kipi-update-build-artifacts.sh', 'bash -c \'o=$(python3 -m pytest -q --ignore=scripts --ignore=.claude --ignore=plugins/kipi-core/kipi-mcp --ignore=plugins/kipi-design 2>&1); printf "%s\\n" "$o" | tail -1; printf "%s\\n" "$o" | grep -Eq "^3 failed, 357 passed, 1 skipped" && [ "$(printf "%s\\n" "$o" | grep -c "^FAILED plugins/prd-os/tests/test_propagation.py::test_rsync_block_excludes_protected_path")" -eq 3 ]\'']
- disallowed_files: []
