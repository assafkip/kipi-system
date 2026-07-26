---
id: prd-updater-consolidation-2026-07-26
title: Updater Consolidation
status: draft
created_at: 2026-07-26T05:29:52Z
updated_at: 2026-07-26T05:33:08Z
owner: assafkip
reviewers: []
findings_path: .prd-os/findings/prd-updater-consolidation-2026-07-26-findings.jsonl
---

# Updater Consolidation

Source of record: `q-system/output/plans/updater-consolidation-prompt-2026-07-25.md`.
The four work items, the scope fence, and the DONE list below are the author's,
transcribed. The per-item designs are this PRD's proposal and are what review
should attack.

## Problem

`kipi-update.sh` answers the same question in several places, and those answers
drift apart. Four of the seven bugs fixed on 2026-07-25 were that single defect
wearing different clothes:

| Question answered more than once | Sites | What the drift cost |
|---|---|---|
| What is a plugin? | 284, 301, 440, 1130 + two separate `find`/glob enumerations | `pathspec ... did not match any files` took the whole config sync down on all_points_setup and Prodigy_Gold |
| What does the disposable dry-run copy contain? | 552 (rsync excludes) and 607 (symlink-walk skip set) | Kept in step on 2026-07-25 by passing one list into the other as argv. That is a wire between two lists, not one list |
| What makes a tree too dirty to touch? | 452, 813, 815, 894 | Each guard carries its own notion of founder work vs this sync's own debris |

Separately, the script can write to an instance and then abandon it. 24 places
give up on an instance; **17 of them give up after already writing to it**; 3
clean up; 0 record the instance's state first. Any failure therefore becomes a
stuck instance a human digs out by hand:

- `sp-5f2d2a63` — a failed staging left 43 files staged; every later run then
  refused at the dirty-tree guard.
- `sp-e244e821` — a failed sync left tracked skeleton files modified; a
  different guard, same stuck instance.

## Goals

- Collapse the three duplicated decisions to one answer each, in the shape the
  file already uses for `INSTANCE_OWNED_SUBTREES` (one list at line 54, three
  accessors at 63/68/73, four consumers at 245/867/993/1056).
- Make a failed run leave no damage: one checkpoint before the first write, one
  restore on every write-then-bail path.
- `kipi-update.sh` is SHORTER when this ships. `wc -l` below 1253. A longer
  diff means the task was misunderstood.

## Non-goals

- Running `kipi update` in any form, dry-run or real. The fleet rollout
  completed 2026-07-25; this task never touches an instance.
- Fixing anything inside an instance repo (hooks, symlinks, `.gitignore` drift,
  tracked build artifacts).
- Working the ~73 open spillover items, or the pre-existing red tests.
- Adding any new script, hook, rule, validator, or plugin. This task adds no new
  enforcement surface. The repo grew 125 files against 5 deletions in 90 days;
  that ratio is why this PRD exists.
- Refactoring anything not named in items 1-4, however tempting the adjacency.

## Proposed approach

Items 1-3 are refactoring: behaviour must not change, and the proof is that the
existing suites stay green with no new test. Item 4 is new behaviour and carries
its own reproducer.

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

Consumers:

- 284/304-308: the staging enumeration is re-rooted **per managed plugin**
  instead of over `plugins/` wholesale. That makes line 301's `[ -d ]` guard
  structurally impossible to need, so it is deleted rather than rewired.
- 440: `config_source_manages` calls `is_managed_plugin_path`.
- 1130: `[ -d "$SKELETON_PLUGIN_ROOT" ]`; 1132's glob becomes
  `managed_plugin_names`.

Behaviour argument (each case must stay identical, and review should check all
three): a loose file at `plugins/README.md` was enumerated then rejected by the
`[ -d ]` test, and is now simply not enumerated — same outcome. A dangling
top-level symlink was enumerated as `-type l` then rejected, and is now not
enumerated — same outcome. A symlink to a real directory is matched by `*/`,
and `find -P` on that starting point still reports the link without descending —
same path staged.

### Item 2 — one answer to "what the disposable copy contains"

The rsync that builds the model and the symlink walk that vets it must agree
exactly. A path the rsync skips cannot be reached by a write, so refusing on a
symlink inside it blocks the instance forever (personal-brand's broken canonical
links refused cole-gtm). A path the walk skips but the rsync copies is unvetted.

One producer, cached per instance root so two callers cannot observe two
different trees:

```sh
MODEL_SKIPPED_ROOT=""; MODEL_SKIPPED_PATHS=()
model_skip_scan()          # populates MODEL_SKIPPED_PATHS for $1 (cached)
model_rsync_excludes()     # calls model_skip_scan, projects to --exclude flags
```

`MODEL_EXCLUDES` is filled from `model_rsync_excludes`; the symlink walk reads
`MODEL_SKIPPED_PATHS` after the same scan. Neither list is derived from the
other. The submodule carve-out (tracked-ness is the line, not nested-ness —
scar: Alice's three submodules under `q-investigate/tools/`) moves into the
producer unchanged.

Proved by the existing `q-system/.q-system/scripts/test/test-kipi-update-safety.sh`.

### Item 3 — one answer to "what makes a tree too dirty to touch?"

One predicate, callers supply the evidence they have:

```sh
# $1 = path in the instance, $2 = the file the skeleton would write there,
#      or "" when the caller cannot name one.
is_instance_wip()
```

It answers the question all four guards ask: is this the founder's work, or is
it this sync's own debris? Debris is a regenerable build artifact
(`.git/`, `__pycache__/`, `*.pyc`, `.venv/`, `.pytest_cache/`) or a file
byte-identical to what the skeleton is about to write.

**Behaviour preservation is the whole risk here.** The q-system collision scan
(894) gains the build-artifact carve-out, which is a no-op: `*.pyc` and
`__pycache__` are already filtered at line 869, and the skeleton ships no
`.venv`/`.git`/`.pytest_cache` under `q-system/`, so `[ -e "$source_path" ]` was
already false for those. The config collision scan (452) passes `""` as the
counterpart, so it does NOT gain the byte-identical carve-out and its behaviour
is unchanged. Excusing byte-identical residue at the config site is the same bug
class as `sp-5f2d2a63` and is worth fixing, but it is a behaviour change and
therefore goes to the ledger, not this diff.

### Item 4 — checkpoint and restore

Record HEAD, the index, and the untracked file list before touching an instance.
On any of the 17 write-then-bail paths, restore that state, then report the
failure. One chokepoint, not 17 patches.

```sh
checkpoint_instance()   # HEAD, a copy of .git/index, `ls-files -z --others`
restore_instance()      # rewind HEAD if the run committed; restore the index;
                        # `git checkout -- .`; delete only untracked paths that
                        # appeared after the checkpoint
```

The dirty-tree guard already proved the tree was clean before the first write,
so discarding what this run wrote is exact restoration, not data loss. No
`git reset --hard`, no `git clean`: HEAD moves with `reset --soft`, the index is
restored by copying the saved file (the shape `guarded_commit` already uses at
line 406), and tracked files come back via `git checkout -- .`.

Must cover `sp-5f2d2a63` (failed staging leaves the index dirty) and
`sp-e244e821` (failed sync leaves tracked skeleton files modified). Both get a
reproducer that is red before the fix.

## Risks and rollback

| Risk | Mitigation |
|---|---|
| A "consolidation" silently changes behaviour, and the fleet finds out on the next real run | Items 1-3 add no test: the bar is that the existing suites stay green unchanged. Every behaviour-identity claim above is enumerated case by case for review to attack |
| `restore_instance` deletes a founder file | It deletes only paths that are untracked NOW and were absent from the checkpoint's untracked list. Never a recursive delete of a directory it did not observe being created |
| `git checkout -- .` discards real work | It runs only after the dirty-tree guard proved the tree clean at checkpoint time, and only on a bail path |
| The cached prd-os runner (0.1.0) differs from the skeleton copy by ~161 lines | Captured as `sp-5a75214b`. This PRD drives the state machine with the cached copy, which is the live load path and the one the plan's `prd_runner.py:556` reference matches |
| Rollback | Single file plus one test file; `git revert` of the per-issue commits. No instance is touched, so there is no fleet-side rollback |

## Open questions

- The plan states a skeleton baseline of 7 failed / 476 passed / 1 skipped. No
  invocation reproduces those numbers. What runs reproducibly is recorded below;
  the 4 unaccounted failures need either the real command or a correction.

## Verification baseline (recorded 2026-07-26, before any edit)

```
python3 -m pytest -q --ignore=scripts --ignore=.claude \
  --ignore=plugins/kipi-core/kipi-mcp --ignore=plugins/kipi-design
  -> 3 failed, 357 passed, 1 skipped
```

The 3 are `test_propagation.py::test_rsync_block_excludes_protected_path`
[`/memory/`, `/output/`, `/my-project/`] — the pre-existing trio the plan names,
asserting literal `--exclude="/my-project/"` strings that commit `98e6284`
replaced with `$(rsync_owned_excludes)`. Not to be chased. The bar is: still
exactly these 3, and no others.

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

- [ ] `grep -c 'SCRIPT_DIR/plugins' kipi-update.sh` shows one definition plus
      its callers, not four independent `[ -d ... ]` checks
- [ ] The rsync exclude list and the symlink-check skip list come from one shell
      function; no argv hand-off between them
- [ ] The four dirty-tree guards share one predicate
- [ ] A pre-run checkpoint exists, and every one of the 17 write-then-bail paths
      restores it
- [ ] `wc -l kipi-update.sh` is LOWER than 1253
- [ ] Tests: still exactly the same 3 pre-existing failures, 357 passed
- [ ] All 8 updater shell suites green
- [ ] `git status` clean; the PRD is archived

## Issues

```json
[
  {
    "id": "issue-updater-one-plugin-answer-2026-07-26",
    "title": "One answer to what is a plugin",
    "priority": "p1",
    "allowed_files": ["kipi-update.sh"],
    "required_checks": [
      "bash q-system/.q-system/scripts/test/test-kipi-update-safety.sh",
      "bash q-system/.q-system/scripts/test/test-kipi-update-build-artifacts.sh",
      "python3 -m pytest -q --ignore=scripts --ignore=.claude --ignore=plugins/kipi-core/kipi-mcp --ignore=plugins/kipi-design"
    ],
    "acceptance": "SKELETON_PLUGIN_ROOT defined once; managed_plugin_names and is_managed_plugin_path are the only deciders; the staging enumeration is re-rooted per managed plugin and line 301's [ -d ] guard is deleted; grep -c 'SCRIPT_DIR/plugins' kipi-update.sh == 1; no test added; baseline unchanged."
  },
  {
    "id": "issue-updater-one-model-manifest-2026-07-26",
    "title": "One answer to what the disposable copy contains",
    "priority": "p1",
    "allowed_files": ["kipi-update.sh"],
    "required_checks": [
      "bash q-system/.q-system/scripts/test/test-kipi-update-safety.sh",
      "bash q-system/.q-system/scripts/test/test-kipi-update-dry-final-state.sh",
      "python3 -m pytest -q --ignore=scripts --ignore=.claude --ignore=plugins/kipi-core/kipi-mcp --ignore=plugins/kipi-design"
    ],
    "acceptance": "model_skip_scan is the single producer, cached per instance root; MODEL_EXCLUDES comes from model_rsync_excludes and the symlink walk reads MODEL_SKIPPED_PATHS; neither list derives from the other; the submodule carve-out is preserved verbatim; no test added; baseline unchanged."
  },
  {
    "id": "issue-updater-one-wip-predicate-2026-07-26",
    "title": "One answer to what makes a tree too dirty to touch",
    "priority": "p1",
    "allowed_files": ["kipi-update.sh"],
    "required_checks": [
      "bash q-system/.q-system/scripts/test/test-kipi-update-safety.sh",
      "bash q-system/.q-system/scripts/test/test-kipi-update-preservation-failure.sh",
      "python3 -m pytest -q --ignore=scripts --ignore=.claude --ignore=plugins/kipi-core/kipi-mcp --ignore=plugins/kipi-design"
    ],
    "acceptance": "is_instance_wip is the single predicate behind the guards at 452, 815 and 894; the config site passes an empty counterpart so it does not gain the byte-identical carve-out; the q-system site's new build-artifact carve-out is argued no-op case by case; no test added; baseline unchanged."
  },
  {
    "id": "issue-updater-checkpoint-restore-2026-07-26",
    "title": "Checkpoint the instance and restore it on every write-then-bail path",
    "priority": "p0",
    "allowed_files": [
      "kipi-update.sh",
      "q-system/.q-system/scripts/test/test-kipi-update-safety.sh"
    ],
    "required_checks": [
      "bash q-system/.q-system/scripts/test/test-kipi-update-safety.sh",
      "bash q-system/.q-system/scripts/test/test-kipi-update-hook-contract.sh",
      "bash q-system/.q-system/scripts/test/test-kipi-update-preservation-failure.sh",
      "python3 -m pytest -q --ignore=scripts --ignore=.claude --ignore=plugins/kipi-core/kipi-mcp --ignore=plugins/kipi-design"
    ],
    "acceptance": "checkpoint_instance runs before the first write; every one of the 17 write-then-bail paths calls restore_instance; reproducers for sp-5f2d2a63 (index left dirty) and sp-e244e821 (tracked files left modified) are red before the fix and green after; each new assertion is mutation-checked against a deliberately gutted implementation; no git reset --hard and no git clean."
  }
]
```
