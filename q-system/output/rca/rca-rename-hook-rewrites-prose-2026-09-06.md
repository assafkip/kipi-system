# RCA: the fleet sync refused one instance after a rename hook rewrote the comment that documents the rename

**Date:** 2026-09-06
**Trigger:** the founder's `kipi-update.sh --only ASK_AI_consultant` run at 13:37 PDT exited `Failed: 1`; the instance's own pre-commit gate refused the hook's commit (log `~/.config/kipi/consulting-sync-.log`, lines 6-69)
**Surface-fix commit:** edfce56c (PR #312, first commit)
**Structural-fix commit:** 9612a4ce and 65b227bd (PR #312, second and third commits)

## What happened

The pre-rsync rename hook `kipi-update-voiceloop-migrate.py` swaps the old voice-engine package name for the new one in every source file of an instance before the skeleton sync copies `q-system/`, `.claude/` and `plugins/` over it. The engine's own `plugins/kipi-core/voiceloop/__init__.py` names the old package on purpose, in the docstring that documents the rename. Every fleet sync rewrote that docstring in every instance, committed it, and the rsync put the skeleton's copy back, so 22 instances carried a churn commit per sync and nobody saw it. On the one instance whose pre-commit compares the engine to its public mirror, the rewrite was a one-line diff against the mirror, the gate refused the commit, the hook reported `voiceloop migration failed; rsync not started`, and that instance stayed off the sync a second time in one day. The same run had already rewritten and staged the instance's own `automation/export_voice_loop.py`, whose two comments document the same rename.

## Surface symptom

```
voice-loop mirror is STALE: 1 file(s) differ from plugins/kipi-core/voiceloop
  --- mirror/voiceloop/__init__.py
  +++ source/voiceloop/__init__.py
  -why the name changed (2026-08-29): this package was called `voicekit` here and the
  +why the name changed (2026-08-29): this package was called `voiceloop` here and the
consulting: moved=False rewritten=7 renamed=0 committed=False verified=False
  ERROR: voiceloop migration failed; rsync not started
  Updated: 0
  Failed:  1
```

Fleet-wide, the same defect read as `rewritten=1` on every instance in every sync log (fleet-apply-20260906-113342.log.apply), a commit the next rsync undid.

## Surface root cause

`swap_tokens()` at kipi-update-voiceloop-migrate.py:160 (main f7e42353) is a plain `str.replace` over the whole file, applied to every path under the instance except the hook itself and `tests/fixtures/`. It has no notion of prose versus code and no notion of which paths the sync is about to overwrite anyway. The engine's docstring and the exporter's comments carried the old name as documentation, and the swap turned "called `voicekit` here and the exporter renamed it to `voiceloop`" into an identity rename.

## Structural root cause

### Root cause #1

`type: code-defect`

A token rewrite that cannot tell prose from code will erase the record of the rename it performs, because the record has to name the old token. "Skip comments" by regex cannot fix it: the old name legitimately appears in string literals that are module paths, which is exactly what must migrate. The classifier has to be the language's own tokenizer and parser (COMMENT tokens, first-statement STRING docstrings), and the hook did not have one.

### Root cause #2

`type: implicit-contract`

The hook ran ahead of an rsync that overwrites a known set of paths, and rewrote those same paths. Nothing stated the contract "a path the sync delivers is the sync's, not the migration's", so the hook did work the next step undid on every run, fleet-wide, and reported it as success. The first fix keyed that set on "exists in the skeleton", which the reviewer showed differs from the delivered set at `INSTANCE_OWNED_SUBTREES`, the skeleton root, the merged `.claude/settings.json` and `PLUGIN_COPY_EXCLUDES`. The delivered set has to be derived from the updater's own arrays and the instance's `subtree_prefix`.

### Root cause #3

`type: missing-test`

The hook's tests built fixtures whose engine init contained no token (`VERSION = 1`) and whose q-system tree was empty, so "already migrated instance is untouched" passed while the real engine init carried the old name in its docstring. No test ran the hook over a tree shaped like the skeleton it ships with, and no fleet-side check noticed a per-sync commit that the next sync reverted.

## Verification

- Ran `python3 -m pytest -q q-system/.q-system/scripts/test_voiceloop_migrate.py` on 65b227bd: 38 passed. Ran the three updater test files together: 53 passed.
- Ran a mutation with `_delivered_by_sync` forced to `False` in a scratch copy: exactly the three delivery tests failed, 30 passed; with `_prose_spans` removed (in-suite negative test), the docstring IS rewritten into the identity rename, so the classifier is what holds the line.
- Ran plan mode (read-only, the same `--repo` call the updater makes) of main's hook and of 65b227bd over the live refused instance after its exporter was restored: main wants 8 rewrites (the engine init, six skeleton-delivered q-system files, the exporter); 65b227bd wants 0, `needs_work` False, 1165 paths reported as delivered, no warnings, instance tree untouched by both runs (`git status` before and after identical).
- Ran the shadow check on the hook: 10 findings, identical to main; one new parameter rebind caught and renamed before the first commit.
- Confirmed the array parse against the owner: the test evaluates `INSTANCE_OWNED_SUBTREES` and `PLUGIN_COPY_EXCLUDES` with bash and got the same seven and seven entries the Python parser reads.

## Contributing factors

- The refusal was visible on exactly one instance: the other 22 have no gate that compares the engine to anything, so the churn commit passed everywhere and the defect surfaced only where a mirror gate existed.
- The updater removes `.git/index.lock` unconditionally before every sync and abandons an instance with its staged rewrites in place (sp-2c1bcc3f, sp-9ec528aa), so the aborted run left the exporter's corrupted rewrite staged for thirteen minutes and the first two readings of "nothing was written" were wrong.
- The hook's `staged_rewrites` recovery reads a staged edit that removes the token as its own interrupted work, so the leftover would have been committed by the next apply under the migration's message.
- The migration commit runs the instance's full pre-commit (`verify.sh --staged`, ~50 s), so each refused attempt cost a founder-minted token and a round trip.

## Fixes shipped

- Surface fix: a path the skeleton ships is never rewritten (edfce56c). Stopped the churn and the refusal for the engine init on the instance measured, and turned out to be the wrong set (see root cause #2).
- Structural fix: prose in a `.py` file is classified with the tokenizer and parser and never rewritten; an unparseable `.py` carrying the token refuses the instance instead of being swapped blind (9612a4ce). The exemption is the set the sync delivers, derived from the updater's own two exclude arrays and the instance's registry prefix, with a test that compares the derivation with bash's evaluation (65b227bd).

## Action items

- [x] Prose-aware swap for `.py`, with the exporter shape as an exact-text test — owner: this PR — type: code
- [x] Delivered-set exemption derived from `kipi-update.sh`'s arrays and the registry prefix — owner: this PR — type: code
- [x] Fixtures mirror the real collisions (docstring in the shipped init, code in the shipped helper) and a negative twin for each rule — owner: this PR — type: test
- [ ] The updater never deletes a `.git/*.lock` younger than the instance's pre-commit budget and refuses the instance instead (sp-2c1bcc3f) — owner: sana — type: gate
- [ ] An abandoned instance is left with nothing staged by the updater (sp-9ec528aa) — owner: sana — type: code
- [ ] A fleet-side check that a per-sync commit is not reverted by the same sync's rsync (the churn signature `rewritten=N` every run) — owner: sana — type: test
- [ ] Blanket swap on the non-`.py` REWRITE_EXTS: decide whether shell comments get a classifier or stay as documented — owner: sana — type: code

## Lessons

- A rename tool that rewrites prose erases the record of the rename; the record has to name the old token, so the classifier must be the language's own parser, not a regex over comments.
- A migration that runs ahead of a sync must exempt exactly the set the sync delivers, derived from the sync's own exclude lists, never from "exists upstream": the two sets differ where instance-owned templates, root files and merged configs live.
- A per-run commit that the next run reverts is a defect with a silent signature (`rewritten=1` forever); a gate on one instance was the only thing that turned it into an error.
- "Nothing was written" needs `git status` over the whole tree, not over the paths the dirty rule watches; the aborted run's write sat in `automation/`.
