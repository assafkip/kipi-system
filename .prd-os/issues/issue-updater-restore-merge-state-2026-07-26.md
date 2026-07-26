---
id: issue-updater-restore-merge-state-2026-07-26
title: Restore clears merge and rebase state the checkpoint did not record
status: closed
priority: p1
parent_prd: prd-updater-consolidation-2026-07-26
allowed_files:
  - kipi-update.sh
  - q-system/.q-system/scripts/test/test-kipi-update-safety.sh
disallowed_files: []
required_checks:
  - bash q-system/.q-system/scripts/test/test-kipi-update-safety.sh
  - bash q-system/.q-system/scripts/test/test-kipi-update-hook-contract.sh
  - bash -c 'o=$(python3 -m pytest -q --ignore=scripts --ignore=.claude --ignore=plugins/kipi-core/kipi-mcp --ignore=plugins/kipi-design 2>&1); printf "%s\n" "$o" | tail -1; printf "%s\n" "$o" | grep -Eq "^3 failed, 357 passed, 1 skipped" && [ "$(printf "%s\n" "$o" | grep -c "^FAILED plugins/prd-os/tests/test_propagation.py::test_rsync_block_excludes_protected_path")" -eq 3 ]'
required_reviews: []
bypass_check: "test \"$(grep -v '^[[:space:]]*#' kipi-update.sh | grep -c 'instance_rebase_in_flight')\" -eq 3 && test \"$(grep -v '^[[:space:]]*#' kipi-update.sh | grep -c 'CHECKPOINT_DIR/inflight')\" -eq 3 && grep -v '^[[:space:]]*#' kipi-update.sh | grep -q 'path-format=absolute --git-path'"
---
<!-- generated-by: prd_split.py prd=prd-updater-consolidation-2026-07-26 finding=finding-5 at=2026-07-26T05:57:44Z -->

# Restore clears merge and rebase state the checkpoint did not record

## Context

Parent PRD: `.prd-os/prds/prd-updater-consolidation-2026-07-26.md`

## Acceptance

Runs LAST, after the restore chokepoint exists. restore_instance removes MERGE_HEAD, CHERRY_PICK_HEAD, rebase-merge/ and rebase-apply/ when the checkpoint did not record them; a fixture leaves the instance mid-merge on the direct-clone fall-through path (:840-846 has no continue, so bails :1083/:1178 run with MERGE_HEAD set whenever git merge --abort fails), runs the restore, and asserts the NEXT commit has one parent rather than two; the assertion checks commit parents, not `git status`, because status reports clean with MERGE_HEAD set, which is the whole defect.

## Amendments

### 2026-07-26T07:17:48Z
Reason: Acceptance and bypass_check both assumed restore must remove MERGE_HEAD and CHERRY_PICK_HEAD. Measurement (verify-issue5-states.sh) shows the mixed reset that issue 4 shipped ALREADY clears both -- merge: MERGE_HEAD -> none; cherry-pick: CHERRY_PICK_HEAD -> none; only rebase-merge survives. finding-5 was written against the PRD's SOFT reset, which does not clear them; issue 4 changed that for an unrelated reason (rewinding landed commits broke hook-contract). Implementing MERGE_HEAD/CHERRY_PICK_HEAD removal now would be dead code. Narrowed to the rebase case. The old bypass_check grepped for the string CHERRY_PICK_HEAD, which my explanatory COMMENT contains, so it would have passed for the wrong reason; replaced with a non-comment count of the rebase-state check and its two abort sites.

Before:
- allowed_files: ['kipi-update.sh', 'q-system/.q-system/scripts/test/test-kipi-update-safety.sh']
- required_checks: ['bash q-system/.q-system/scripts/test/test-kipi-update-safety.sh', 'bash q-system/.q-system/scripts/test/test-kipi-update-hook-contract.sh', 'bash -c \'o=$(python3 -m pytest -q --ignore=scripts --ignore=.claude --ignore=plugins/kipi-core/kipi-mcp --ignore=plugins/kipi-design 2>&1); printf "%s\\n" "$o" | tail -1; printf "%s\\n" "$o" | grep -Eq "^3 failed, 357 passed, 1 skipped" && [ "$(printf "%s\\n" "$o" | grep -c "^FAILED plugins/prd-os/tests/test_propagation.py::test_rsync_block_excludes_protected_path")" -eq 3 ]\'']
- disallowed_files: []

After:
- allowed_files: ['kipi-update.sh', 'q-system/.q-system/scripts/test/test-kipi-update-safety.sh']
- required_checks: ['bash q-system/.q-system/scripts/test/test-kipi-update-safety.sh', 'bash q-system/.q-system/scripts/test/test-kipi-update-hook-contract.sh', 'bash -c \'o=$(python3 -m pytest -q --ignore=scripts --ignore=.claude --ignore=plugins/kipi-core/kipi-mcp --ignore=plugins/kipi-design 2>&1); printf "%s\\n" "$o" | tail -1; printf "%s\\n" "$o" | grep -Eq "^3 failed, 357 passed, 1 skipped" && [ "$(printf "%s\\n" "$o" | grep -c "^FAILED plugins/prd-os/tests/test_propagation.py::test_rsync_block_excludes_protected_path")" -eq 3 ]\'']
- disallowed_files: []
