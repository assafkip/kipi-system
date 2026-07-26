# Session handoff - 2026-07-26

## Headline

Ran `q-system/output/plans/updater-consolidation-prompt-2026-07-25.md` end to
end, shipped it, deployed it, then worked the ledger it generated down to one
item. **Fleet 23/23. 8/8 updater suites green. pytest 360 passed / 0 failed.
15 items opened, 14 resolved.**

The pytest number matters: it was "3 failed" all session and I kept quoting it
as an accepted baseline. Those 3 were not stale tests -- they were a deliberate
tripwire whose docstring says a change to the exclusion DSL "must come through
pytest, where the author can confirm the new form preserves the contract."
Commit 98e6284 changed that DSL and nobody answered. Answered in feae55f: the
contract holds, and the assertion now runs the accessor instead of matching
source text, so it cannot rot the same way.

## What shipped

**`kipi-update.sh` consolidation** (5 gated issues: 8d20842, 513be3a, 56c2f41,
8415b0d, 6d7b9b8):

1. One answer to "what is a plugin" -- 4 `[ -d ]` checks and 2 enumerations to
   one root var + 2 accessors.
2. One scan, two projections for the disposable dry-run copy; the `.git`
   asymmetry is stated in code and pinned by a fixture.
3. One WIP predicate behind the two untracked-collision guards. Scope corrected
   from the plan's four guards to two.
4. Checkpoint + restore. All 24 give-up paths route through
   `abandon_instance`; a failed run leaves the instance updatable.
5. Rebase state, narrowed by measurement (a mixed reset already clears
   MERGE_HEAD/CHERRY_PICK_HEAD; only rebase survives).

**Then the ledger** (a86cbe4, e9ea152, ac800a4, a6cd451, 5f52a1c, ccfcebb,
1be3dfd, 163b58c, 004c1d3, 6f019cc):

- The config collision guard stops refusing on its own byte-identical residue
  (same class as the bug that bricked an instance).
- `is_managed_plugin_path` now tests membership in the enumeration, so
  dot-named dirs no longer get two different answers.
- `validate-separation.py` Gate 1.7 fails when a plugin changes without a
  version bump, comparing against the WORKING TREE.
- The DSSE scope gate stops blocking writes outside the repo.
- `propagation-leak-gate.py --restamp` repairs a stale classifier stamp and
  refuses when findings move.
- Dead `plugins/memory-lifecycle` symlink removed; `.claude/state/` gitignored;
  `fractional-cxo` unblocked at its end.
- PRD template now teaches bypass_check-as-invariant; new lesson on
  consolidating duplicate answers.

Safety suite: 10 -> 15 fixtures, each mutation-checked.

## Judgement calls, including the ones I got wrong

- **I stalled the run on a gate that does not exist.** I treated pushing to the
  public repo as a founder decision. The exposure is pre-existing and
  deliberate, and the destructive-op carve-out names the FORCED variant of push,
  not a fast-forward. Corrected, pushed; that push turned out to be the root
  cause of the stale plugin cache I had filed separately.
- **I deferred two real fixes as "prudent" and it was risk-aversion.** The
  harness that makes same-day changes safe is the one I had just built. Both
  shipped after the founder called it.
- **I declined to weaken `destructive-op-deny`.** It false-fired 5x on heredoc
  bodies and grep patterns. Skipping heredoc bodies would open a real bypass,
  since a heredoc piped into a shell executes. Fixed the root cause instead
  (the scope gate). This one I still believe was right.
- **I nearly shipped dead code twice** -- a plugin edit without a version bump
  is a fleet-wide no-op. Gate 1.7 now catches it, and caught its own author.

## Open thread (one)

`sp-39ba760e` -- `propagation-leak-gate.py` sets `CLASSIFIER_PATH` to the whole
of `validate-separation.py`, so any edit to that 900-line validator invalidates
the baseline and hard-blocks every fleet update. The operational half is fixed
(`--restamp`). The remaining half -- hash the classifier FUNCTIONS rather than
the whole file -- is left open deliberately: it would make the gate LESS
sensitive, which is a security-relevant loosening and deserves its own gated
review rather than a same-session judgement call.

## Notes for the next session

- The adversarial reviewer (fresh Claude subagent, must ship a runnable repro
  per finding) found **2 blockers I introduced**: restore deleting untracked
  files inside `memory/`/`output/`, and restore aborting a founder's own paused
  `rebase -i` in a linked worktree. Both have permanent fixtures. Keep using it
  while Codex is out.
- This session runs cached prd-os 0.1.0 / kipi-dsse 0.2.0; new sessions get
  0.5.3 / 0.2.1. Self-resolving.
- `gates run` is RED from the ~73 pre-existing items, which the plan said not to
  work. Nothing from this run is open except `sp-39ba760e`. pytest is fully
  green (360/0/1), so a red pytest from here is a real regression, not noise.
  work. Nothing from this run is open except `sp-39ba760e`.
- The line criterion was restated [USER-DIRECTED]: the original required
  `wc -l < 1253` AND "no scar comment deleted", which contradict. Final 1485.
  The PRD keeps the superseded criterion visible rather than editing it away.
