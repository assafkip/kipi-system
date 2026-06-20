---
id: kipi-update-safety
title: kipi update fail-safe + transparent: deterministic tmp-dir untracked-snapshot before rsync --delete (covers gitignored-synced; H2), and a real rsync -ain itemized --dry from git archive HEAD replacing the file-count heuristic (H4)
status: closed
priority: p1
parent_prd: prd-brief-adopt-items-2026-06-20
allowed_files:
  - kipi-update.sh
  - q-system/.q-system/scripts/test/test-kipi-update-safety.sh
disallowed_files: []
required_checks:
  - bash q-system/.q-system/scripts/test/test-kipi-update-safety.sh
required_reviews: []
bypass_check: "bash q-system/.q-system/scripts/test/test-kipi-update-safety.sh"
---
<!-- generated-by: prd_split.py prd=prd-brief-adopt-items-2026-06-20 finding=finding-1 at=2026-06-20T01:42:14Z -->

# kipi update fail-safe + transparent: deterministic tmp-dir untracked-snapshot before rsync --delete (covers gitignored-synced; H2), and a real rsync -ain itemized --dry from git archive HEAD replacing the file-count heuristic (H4)

## Context

Parent PRD: `.prd-os/prds/prd-brief-adopt-items-2026-06-20.md`

## Acceptance

- [ ] Before the `rsync -a --delete` in `kipi-update.sh`, snapshot the instance's UNTRACKED files under `$prefix/` to a tmp dir via `git ls-files --others` (which lists untracked files INCLUDING gitignored ones; covers q-system/sources/ that `git stash -u` misses). After the sync + commit, restore any snapshotted file the sync DELETED (absent post-sync). No `git stash`. No data loss on the unhappy path.
- [ ] Replace the `--dry` SKEL_COUNT/INST_COUNT file-count heuristic with `rsync -ain --delete` built from the SAME `git archive HEAD` source AND the same excludes as the real run, printing the actual changed/deleted file list (cannot drift from the real run).
- [ ] `test-kipi-update-safety.sh`: a fixture untracked file in a gitignored-but-synced path survives an update (round-trips); the `--dry` output lists actual changed/deleted files (not just counts). Offline, self-contained.
- [ ] required_check passes.
