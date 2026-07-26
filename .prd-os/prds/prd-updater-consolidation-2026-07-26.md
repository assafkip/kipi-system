---
id: prd-updater-consolidation-2026-07-26
title: Updater Consolidation
status: archived
created_at: 2026-07-26T05:29:52Z
updated_at: 2026-07-26T07:31:13Z
owner: assafkip
reviewers: []
findings_path: .prd-os/findings/prd-updater-consolidation-2026-07-26-findings.jsonl
codex_reviewed_at: 2026-07-26T05:52:19Z
---

# Updater Consolidation

Source of record: `q-system/output/plans/updater-consolidation-prompt-2026-07-25.md`.
The four work items, the scope fence, and the DONE list below are the author's,
transcribed. The per-item designs are this PRD's proposal.

**Revision 2 (2026-07-26), after review.** Six findings, all accepted, all
folded in below. The three that changed the design are marked **[R]**: item 2
gained a second projection because the two lists it unifies do not have the
same membership; item 3 shrank from four guards to two because the tracked-tree
check cannot take the predicate; item 4 gained untracked-content preservation
because nothing in the original design could undo an `rsync --delete`.

## Problem

`kipi-update.sh` answers the same question in several places, and those answers
drift apart. Four of the seven bugs fixed on 2026-07-25 were that single defect
wearing different clothes:

| Question answered more than once | Sites | What the drift cost |
|---|---|---|
| What is a plugin? | 284, 301, 440, 1130 + two separate `find`/glob enumerations | `pathspec ... did not match any files` took the whole config sync down on all_points_setup and Prodigy_Gold |
| What does the disposable dry-run copy contain? | 552 (rsync excludes) and 607 (symlink-walk skip set) | Kept in step on 2026-07-25 by passing one list into the other as argv. That is a wire between two lists, not one list |
| Which untracked file is work in progress? | 452 and 894 | Each carries its own notion of founder work vs this sync's own debris |

Separately, the script can write to an instance and then abandon it. **24
places give up on an instance and none of them record its state first.** Any
failure therefore becomes a stuck instance a human digs out by hand:

- `sp-5f2d2a63` — a failed staging left 43 files staged; every later run then
  refused at the dirty-tree guard.
- `sp-e244e821` — a failed sync left tracked skeleton files modified; a
  different guard, same stuck instance.

Both are reproduced by one fixture (`repro-item4-stuck-instance.sh`, red
against the current script): the instance's own `pre-commit` hook rejects the
updater's commit, and the run bails at :1033 leaving `M q-system/tracked.md`
plus three staged adds. A second run then refuses with `dirty working tree`.

### On the plan's "17 write-then-bail paths"

Not reproducible, and not the right frame. `grep -c -F 'FAIL=$((FAIL + 1))'`
confirms **24** give-up sites. After the first worktree write (rsync at :992)
there are 7; after the first `.git` write (stale-lock removal at :791) there
are 16. Nothing yields 17. Since `restore_instance` is a no-op when nothing was
written, the design covers **all 24** and the counting argument disappears.

## Goals

- Collapse the duplicated decisions to one answer each, in the shape the file
  already uses for `INSTANCE_OWNED_SUBTREES` (one list at :54, three accessors
  at :63/:68/:73, four consumers at :245/:867/:993/:1056).
- Make a failed run leave no damage: one checkpoint before the first write, one
  restore chokepoint every give-up path routes through.
- `kipi-update.sh` is SHORTER when this ships. `wc -l` below 1253.

### Where the shrink comes from  **[finding-6]**

Stated explicitly, because "a longer diff means the task was misunderstood"
must not fire on a correct implementation. Measured by
`verify-shrink-claim.py` against the real file, not estimated:

```
give-up sites (FAIL++)        = 24
lines consumed by the rituals = 127     (4 to 7 lines each)

item 4:  -127 ritual  +24 calls  +9 abandon_instance
         +12 checkpoint_instance  +25 restore_instance   = -57
items 1-3 (conservative)                                 = -12
projected wc -l = 1253 - 57 - 12 = 1184     (margin +69)
```

The funding source is the 127 lines of repeated bail ritual, not the 237
comment lines. **No scar comment is deleted to hit this number.** Every guard's
`why` survives the diff; a comment that outlives its guard moves onto the
consolidated one.

## Non-goals

- Running `kipi update` in any form, dry-run or real. The fleet rollout
  completed 2026-07-25; this task never touches an instance.
- Fixing anything inside an instance repo (hooks, symlinks, `.gitignore` drift,
  tracked build artifacts).
- Working the ~73 open spillover items, or the pre-existing red tests.
- Adding any new script, hook, rule, validator, or plugin. This task adds no new
  enforcement surface. (A new *fixture inside an existing suite* is not a new
  enforcement surface; items 2 and 4 each add one, and say why below.)
- Refactoring anything not named in items 1-4, however tempting the adjacency.

## Proposed approach

Items 1-3 are refactoring: behaviour must not change. Item 4 is new behaviour
and carries its own reproducer.

### Item 1 — one answer to "what is a plugin?"

One root variable plus two accessors; `$SCRIPT_DIR/plugins` appears literally
once in the file.

```sh
SKELETON_PLUGIN_ROOT="$SCRIPT_DIR/plugins"

managed_plugin_names()      # the `*/` glob resolves symlinks, so a dangling
                            # top-level link never appears -- neither the copy
                            # nor the staging can see it
is_managed_plugin_path()    # repo-relative path -> top segment -> [ -d ... ]
```

Consumers: the staging enumeration at :284/:304-308 is re-rooted **per managed
plugin** instead of over `plugins/` wholesale, which makes :301's `[ -d ]` guard
structurally impossible to need, so it is deleted rather than rewired; :440
calls `is_managed_plugin_path`; :1130 tests `SKELETON_PLUGIN_ROOT` and :1132's
glob becomes `managed_plugin_names`.

Behaviour argument, three cases review must check: a loose file at
`plugins/README.md` was enumerated then rejected by `[ -d ]`, and is now not
enumerated — same outcome. A dangling top-level symlink was enumerated as
`-type l` then rejected, same outcome. A symlink to a real directory is matched
by `*/`, and `find -P` on that starting point still reports the link without
descending — same path staged.

### Item 2 — one answer to "what the disposable copy contains"  **[R] [finding-1]**

The rsync that builds the model and the symlink walk that vets it must agree.
A path the rsync skips cannot be reached by a write, so refusing on a symlink
inside it blocks the instance forever (personal-brand's broken canonical links
refused cole-gtm). A path the walk skips but the rsync copies is unvetted.

**They do not currently have the same membership, and one list cannot serve
both.** `MODEL_EXCLUDES` is seeded at :552 with `--exclude=".git"`, while the
walk at :579-651 does not skip `.git` — a dangling link at `.git/hooks/*` is
refused today. Collapsing to a single list would either delete that refusal (a
silent behaviour change at a safety guard) or leave the lists divergent, which
is the defect this item exists to kill. Compounding it, `.git` enters the model
on one branch only (`cp -a "$path/.git"` at :683, under the `[ -d "$path/.git" ]`
test at :679) — a branch chosen *after* both call sites.

So: one scan, two named projections, and the asymmetry is stated in code rather
than emergent.

```sh
MODEL_SKIPPED_ROOT=""; MODEL_SKIPPED_PATHS=()
model_skip_scan()          # the ONE scan: untracked nested repos, cached per
                           # instance root so two callers cannot see two trees
model_rsync_excludes()     # projection A: --exclude flags, PLUS .git
model_walk_skips()         # projection B: paths only, WITHOUT .git --
                           # the walk still vets the instance's own .git
```

Both projections read `MODEL_SKIPPED_PATHS`; neither derives from the other,
and `.git`'s asymmetry lives in one named place with the reason attached. The
submodule carve-out (tracked-ness is the line, not nested-ness — scar: Alice's
three submodules under `q-investigate/tools/`) moves into the scan unchanged.

New fixture required, because no fixture in any of the 8 suites plants a link
under `.git/` (`grep -n 'ln -s'` across all 8 returns none), so the asymmetry is
currently unpinned and a future consolidation would silently erase it. The
fixture asserts today's behaviour, not new behaviour.

### Item 3 — one answer to "which untracked file is work in progress?"  **[R] [finding-2]**

**Scope corrected: two guards, not four.** The plan named :452, :813, :815 and
:894. :813 and :815 are two echoes inside one `if`-block, so that is three
sites; and the block at :808-821 is
`if ! git diff --cached --quiet || ! git diff --quiet` — a whole-tree check that
takes no path and no skeleton counterpart, so the predicate has no arguments to
receive there. Forcing it in is not behaviour-preserving: with the debris
carve-out applied, a TRACKED modified `__pycache__/*.pyc` stops failing the
guard and `stage_q_system_sync`'s `git add -u` at :226 then stages it into the
updater's own commit — exactly what the :808 comment forbids.

**:815 is therefore out of scope and unchanged.** The two guards that genuinely
share a question — "an untracked file sits where the skeleton is about to
write; is that the founder's work?" — are :452 and :894:

```sh
# $1 = path in the instance, $2 = the file the skeleton would write there,
#      or "" when the caller cannot name one.
is_instance_wip()
```

Debris is a regenerable build artifact (`.git/`, `__pycache__/`, `*.pyc`,
`.venv/`, `.pytest_cache/`) or a file byte-identical to what the skeleton is
about to write. The q-system scan (:894) gains the build-artifact carve-out,
which is a no-op: `*.pyc` and `__pycache__` are already filtered at :869, and
the skeleton ships no `.venv`/`.git`/`.pytest_cache` under `q-system/`, so
`[ -e "$source_path" ]` was already false. The config scan (:452) passes `""`,
so it does NOT gain the byte-identical carve-out and its behaviour is
unchanged. Excusing byte-identical residue there is the same bug class as
`sp-5f2d2a63` and worth fixing, but it is a behaviour change and goes to the
ledger, not this diff.

### Item 4 — checkpoint and restore  **[R] [finding-3, finding-5]**

Record the instance's state before touching it; route every give-up path
through one chokepoint that puts it back, then reports.

```sh
checkpoint_instance()   # HEAD, a copy of .git/index, the untracked file list
                        # AND a copy of the untracked BYTES
restore_instance()      # rewind HEAD if the run committed; restore the index;
                        # `git checkout -- .`; restore untracked content;
                        # delete untracked paths absent from the checkpoint;
                        # clear merge/rebase state the checkpoint did not have
abandon_instance()      # restore + cleanup_dry_model + FAIL++ + report
```

**Untracked content, not just a path list [finding-3].** Nothing in a
path-list-only checkpoint can undo an `rsync --delete`. Bails :1000 and :1014
are reached *after* the delete has removed untracked instance files, and the
snapshot holding the only copy (`$SNAP/f/`, created inside `ARCHIVE_TMP` at
:861) is already destroyed by the `rm -r -- "$ARCHIVE_TMP"` at :995/:1009. So
the checkpoint copies bytes, and those two bails restore from the checkpoint
before teardown. Without this, every DONE box ticks while the highest-value
data-loss path ships untouched.

**Merge/rebase state [finding-5].** `reset --soft` does not clear `MERGE_HEAD`,
and `git status` reports clean with it set, so the founder's next commit
silently becomes a merge commit. Reachable on the direct-clone path, which at
:840-846 has no `continue` and falls through to the config sync, so bails
:1083/:1178 run with `MERGE_HEAD` set whenever the `git merge --abort` at :845
fails. `restore_instance` removes `MERGE_HEAD`, `CHERRY_PICK_HEAD`,
`rebase-merge/` and `rebase-apply/` when the checkpoint did not record them.

The dirty-tree guard already proved the tree was clean before the first write,
so discarding what this run wrote is exact restoration, not data loss. No
`git reset --hard` and no `git clean`: HEAD moves with `reset --soft`, the index
is restored by copying the saved file (the shape `guarded_commit` already uses
at :406), tracked files come back via `git checkout -- .`, and untracked
deletions are only ever of paths absent from the checkpoint.

## Issue order  **[finding-4]**

All four issues edit one file, so the order is part of the contract:
**1 → 2 → 3 → 4.** Item 4's chokepoint lands last, on already-consolidated
guards. Issue 3 rewrites :877-897 while issue 4 places restore calls at the
:875/:881/:892 bails inside it, so **issue 4 re-snapshots its scope with
`/issue-amend` after issue 3 closes.** Issue 3's scope correction (dropping
:815) removes the :820 collision entirely. Priorities are p1/p1/p1/p0; p0 marks
item 4 as the highest-value fix, not the first to run.

## Risks and rollback

| Risk | Mitigation |
|---|---|
| A "consolidation" silently changes behaviour | Items 1-3 add no behaviour test; the bar is that existing suites stay green. Every behaviour-identity claim is enumerated case by case. Item 2's one new fixture pins EXISTING behaviour that is currently unpinned |
| `restore_instance` deletes a founder file | It deletes only paths untracked NOW and absent from the checkpoint's untracked list. Never a recursive delete of a directory it did not observe being created |
| `git checkout -- .` discards real work | Runs only after the dirty-tree guard proved the tree clean at checkpoint time, and only on a bail path |
| Checkpoint disk cost: copying untracked bytes per instance | Bounded by what `ls-files --others` returns under the synced prefix; the existing `$SNAP/f/` machinery already does exactly this copy, so the cost is precedented, not new |
| The cached prd-os runner (0.1.0) differs from the skeleton copy by ~161 lines | Captured as `sp-5a75214b`. This PRD drives the state machine with the cached copy, the live load path, which the plan's `prd_runner.py:556` reference matches |
| Rollback | One file plus one test file; `git revert` of the per-issue commits. No instance is touched, so there is no fleet-side rollback |

## Open questions

- The plan states a skeleton baseline of 7 failed / 476 passed / 1 skipped. No
  invocation reproduces those numbers. What runs reproducibly is recorded
  below; the 4 unaccounted failures need either the real command or a
  correction. Not blocking: the bar used here is "the same 3, and no others".

## Verification baseline (recorded 2026-07-26, before any edit)

```
python3 -m pytest -q --ignore=scripts --ignore=.claude \
  --ignore=plugins/kipi-core/kipi-mcp --ignore=plugins/kipi-design
  -> 3 failed, 357 passed, 1 skipped
```

The 3 are `test_propagation.py::test_rsync_block_excludes_protected_path`
[`/memory/`, `/output/`, `/my-project/`] — the pre-existing trio the plan names,
asserting literal `--exclude="/my-project/"` strings that commit `98e6284`
replaced with `$(rsync_owned_excludes)`. Not to be chased.

`--ignore` targets are environment-broken collection errors, not regressions:
`scripts/test_persona_reorg.py` calls `sys.exit(0)` at import;
`plugins/kipi-design/hooks/tests` cannot import `design_room_pipeline`;
`plugins/kipi-core/kipi-mcp/tests` needs its uv environment and passes 688/688
under `uv run python -m pytest -q tests`.

The 8 updater shell suites, all green at baseline and required to stay green:
`test-kipi-update-{safety,build-artifacts,dry-final-state,hook-contract,leak-preflight,preservation-failure}.sh`
in `q-system/.q-system/scripts/test/`, plus
`test-kipi-update-preserve-{integration,scan}.sh` at the repo root.

## Scope fence

Editable: `kipi-update.sh`, its shell suites under
`q-system/.q-system/scripts/test/`, and `.prd-os/` state the commands write
themselves. Anything else means the task was left.

Out-of-scope findings go to the ledger, not the diff:

```bash
python3 plugins/prd-os/scripts/prd_runner.py spillover add \
  --source updater-consolidation --desc "<what it is, concretely>"
```

## DONE

- [ ] `grep -c 'SCRIPT_DIR/plugins' kipi-update.sh` == 1
- [ ] The model rsync excludes and the symlink-walk skips come from one scan via
      two named projections; no argv hand-off between them; `.git`'s asymmetry
      is explicit in code and pinned by a fixture
- [ ] The two untracked-collision guards (:452, :894) share one predicate; the
      tracked-tree check (:815) is unchanged
- [ ] A pre-run checkpoint exists that captures untracked CONTENT, and all 24
      give-up paths route through the restore chokepoint
- [ ] `repro-item4-stuck-instance.sh` goes green, and is mutation-checked
      against a deliberately gutted restore
- [ ] `wc -l kipi-update.sh` is LOWER than 1253, with no scar comment deleted
- [ ] Tests: still exactly the same 3 pre-existing failures, 357 passed
- [ ] All 8 updater shell suites green
- [ ] `git status` clean; the PRD is archived

## Issues

```json
[
  {
    "id": "issue-updater-one-plugin-answer-2026-07-26",
    "finding_id": "finding-7",
    "title": "One answer to what is a plugin",
    "priority": "p1",
    "allowed_files": ["kipi-update.sh"],
    "required_checks": [
      "bash q-system/.q-system/scripts/test/test-kipi-update-safety.sh",
      "bash q-system/.q-system/scripts/test/test-kipi-update-build-artifacts.sh",
      "bash -c 'o=$(python3 -m pytest -q --ignore=scripts --ignore=.claude --ignore=plugins/kipi-core/kipi-mcp --ignore=plugins/kipi-design 2>&1); printf \"%s\\n\" \"$o\" | tail -1; printf \"%s\\n\" \"$o\" | grep -Eq \"^3 failed, 357 passed, 1 skipped\" && [ \"$(printf \"%s\\n\" \"$o\" | grep -c \"^FAILED plugins/prd-os/tests/test_propagation.py::test_rsync_block_excludes_protected_path\")\" -eq 3 ]'"
    ],
    "bypass_check": "test \"$(grep -c 'SCRIPT_DIR/plugins' kipi-update.sh)\" -eq 1",
    "acceptance": "Runs FIRST. SKELETON_PLUGIN_ROOT defined once; managed_plugin_names and is_managed_plugin_path are the only deciders; the staging enumeration is re-rooted per managed plugin and :301's [ -d ] guard is deleted; the three behaviour-identity cases (loose file under plugins/, dangling top-level symlink, symlink-to-real-directory) are each demonstrated unchanged before and after; no test added; baseline unchanged."
  },
  {
    "id": "issue-updater-one-model-scan-2026-07-26",
    "finding_id": "finding-1",
    "title": "One scan, two projections, for what the disposable copy contains",
    "priority": "p1",
    "allowed_files": [
      "kipi-update.sh",
      "q-system/.q-system/scripts/test/test-kipi-update-safety.sh"
    ],
    "required_checks": [
      "bash q-system/.q-system/scripts/test/test-kipi-update-safety.sh",
      "bash q-system/.q-system/scripts/test/test-kipi-update-dry-final-state.sh",
      "bash -c 'o=$(python3 -m pytest -q --ignore=scripts --ignore=.claude --ignore=plugins/kipi-core/kipi-mcp --ignore=plugins/kipi-design 2>&1); printf \"%s\\n\" \"$o\" | tail -1; printf \"%s\\n\" \"$o\" | grep -Eq \"^3 failed, 357 passed, 1 skipped\" && [ \"$(printf \"%s\\n\" \"$o\" | grep -c \"^FAILED plugins/prd-os/tests/test_propagation.py::test_rsync_block_excludes_protected_path\")\" -eq 3 ]'"
    ],
    "bypass_check": "test \"$(grep -c 'model_skip_scan' kipi-update.sh)\" -ge 3",
    "acceptance": "Runs SECOND. model_skip_scan is the single cached scan; model_rsync_excludes and model_walk_skips are two named projections of it, neither derived from the other; .git is in the rsync projection and NOT in the walk projection, with the asymmetry's reason in a comment; a new fixture plants a dangling symlink under the instance's own .git/ and asserts the run still refuses, pinning today's behaviour rather than introducing new behaviour; the submodule carve-out is preserved verbatim; baseline unchanged."
  },
  {
    "id": "issue-updater-one-wip-predicate-2026-07-26",
    "finding_id": "finding-2",
    "title": "One predicate for the two untracked-collision guards",
    "priority": "p1",
    "allowed_files": ["kipi-update.sh"],
    "required_checks": [
      "bash q-system/.q-system/scripts/test/test-kipi-update-safety.sh",
      "bash q-system/.q-system/scripts/test/test-kipi-update-preservation-failure.sh",
      "bash -c 'o=$(python3 -m pytest -q --ignore=scripts --ignore=.claude --ignore=plugins/kipi-core/kipi-mcp --ignore=plugins/kipi-design 2>&1); printf \"%s\\n\" \"$o\" | tail -1; printf \"%s\\n\" \"$o\" | grep -Eq \"^3 failed, 357 passed, 1 skipped\" && [ \"$(printf \"%s\\n\" \"$o\" | grep -c \"^FAILED plugins/prd-os/tests/test_propagation.py::test_rsync_block_excludes_protected_path\")\" -eq 3 ]'"
    ],
    "bypass_check": "test \"$(grep -c 'is_instance_wip' kipi-update.sh)\" -eq 3 && grep -q 'refusing to commit unrelated work' kipi-update.sh",
    "acceptance": "Runs THIRD. is_instance_wip is the single predicate behind :452 and :894 ONLY; the tracked-tree check at :808-821 is NOT touched, and why is comment-anchored (a modified TRACKED .pyc must keep failing that guard, else git add -u at :226 stages it into the updater's own commit); the config site passes an empty counterpart so it does not gain the byte-identical carve-out; the q-system site's new build-artifact carve-out is argued no-op case by case; the deferred config-site byte-identical fix is captured in spillover; no test added; baseline unchanged."
  },
  {
    "id": "issue-updater-checkpoint-restore-2026-07-26",
    "finding_id": "finding-3",
    "title": "Checkpoint the instance and restore it on every give-up path",
    "priority": "p0",
    "allowed_files": [
      "kipi-update.sh",
      "q-system/.q-system/scripts/test/test-kipi-update-safety.sh"
    ],
    "required_checks": [
      "bash q-system/.q-system/scripts/test/test-kipi-update-safety.sh",
      "bash q-system/.q-system/scripts/test/test-kipi-update-hook-contract.sh",
      "bash q-system/.q-system/scripts/test/test-kipi-update-preservation-failure.sh",
      "bash -c 'o=$(python3 -m pytest -q --ignore=scripts --ignore=.claude --ignore=plugins/kipi-core/kipi-mcp --ignore=plugins/kipi-design 2>&1); printf \"%s\\n\" \"$o\" | tail -1; printf \"%s\\n\" \"$o\" | grep -Eq \"^3 failed, 357 passed, 1 skipped\" && [ \"$(printf \"%s\\n\" \"$o\" | grep -c \"^FAILED plugins/prd-os/tests/test_propagation.py::test_rsync_block_excludes_protected_path\")\" -eq 3 ]'"
    ],
    "bypass_check": "test \"$(grep -c -F 'FAIL=$((FAIL + 1))' kipi-update.sh)\" -eq 1",
    "acceptance": "Runs FOURTH, and re-snapshots its scope with /issue-amend after issue 3 closes. checkpoint_instance runs before the first write and copies untracked CONTENT, not only the path list; all 24 give-up paths route through abandon_instance, so FAIL++ appears exactly once in the file; the reproducer for sp-5f2d2a63 and sp-e244e821 is red before and green after; a fixture proves an untracked file deleted by rsync --delete is restored on the :1000 and :1014 bails, which requires restoring before ARCHIVE_TMP teardown; every new assertion is mutation-checked against a deliberately gutted restore; no git reset --hard and no git clean; wc -l kipi-update.sh < 1253 with no scar comment deleted."
  },
  {
    "id": "issue-updater-restore-merge-state-2026-07-26",
    "finding_id": "finding-5",
    "title": "Restore clears merge and rebase state the checkpoint did not record",
    "priority": "p1",
    "allowed_files": [
      "kipi-update.sh",
      "q-system/.q-system/scripts/test/test-kipi-update-safety.sh"
    ],
    "required_checks": [
      "bash q-system/.q-system/scripts/test/test-kipi-update-safety.sh",
      "bash q-system/.q-system/scripts/test/test-kipi-update-hook-contract.sh",
      "bash -c 'o=$(python3 -m pytest -q --ignore=scripts --ignore=.claude --ignore=plugins/kipi-core/kipi-mcp --ignore=plugins/kipi-design 2>&1); printf \"%s\\n\" \"$o\" | tail -1; printf \"%s\\n\" \"$o\" | grep -Eq \"^3 failed, 357 passed, 1 skipped\" && [ \"$(printf \"%s\\n\" \"$o\" | grep -c \"^FAILED plugins/prd-os/tests/test_propagation.py::test_rsync_block_excludes_protected_path\")\" -eq 3 ]'"
    ],
    "bypass_check": "grep -q 'CHERRY_PICK_HEAD' kipi-update.sh",
    "acceptance": "Runs LAST, after the restore chokepoint exists. restore_instance removes MERGE_HEAD, CHERRY_PICK_HEAD, rebase-merge/ and rebase-apply/ when the checkpoint did not record them; a fixture leaves the instance mid-merge on the direct-clone fall-through path (:840-846 has no continue, so bails :1083/:1178 run with MERGE_HEAD set whenever git merge --abort fails), runs the restore, and asserts the NEXT commit has one parent rather than two; the assertion checks commit parents, not `git status`, because status reports clean with MERGE_HEAD set, which is the whole defect."
  }
]
```
