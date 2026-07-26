# Session handoff - 2026-07-26

## Headline

Ran `q-system/output/plans/updater-consolidation-prompt-2026-07-25.md` end to
end: PRD -> adversarial review -> 5 issues -> archive, then proved the result on
real repos and shipped it. **Fleet is 23/23 updated, 0 left tracked-dirty.**

One decision is yours and blocks nothing else: **github.com/assafkip/kipi-system
is PUBLIC** and already publishes `instance-registry.json` (every client
engagement by name and absolute path). Local main is 100 commits ahead of
origin. I did not push. See sp-64f800a4.

## What shipped

`kipi-update.sh`, through 5 gated issues (8d20842, 513be3a, 56c2f41, 8415b0d,
6d7b9b8) plus cleanup (1be3dfd):

1. **One answer to "what is a plugin"** - 4 independent `[ -d ]` checks and 2
   enumerations collapsed to one root var + 2 accessors.
2. **One scan, two projections** for the disposable dry-run copy. The `.git`
   asymmetry is now stated in code (rsync excludes it, the symlink walk must
   not) instead of emergent, and pinned by a new fixture -- nothing across all
   8 suites planted a link under `.git/` before.
3. **One WIP predicate** behind the two untracked-collision guards. Scope was
   corrected from the plan's four guards to two: the tracked-tree check takes
   no path argument, and giving it the debris carve-out would stage a modified
   tracked `.pyc` into the updater's own commit.
4. **Checkpoint + restore.** All 24 give-up paths route through
   `abandon_instance`; the increment appears once in the file. A failed run now
   leaves the instance updatable.
5. **Rebase state**, narrowed by measurement: a mixed reset already clears
   MERGE_HEAD/CHERRY_PICK_HEAD, so only rebase survives and only that is
   handled.

Safety suite grew 10 -> 14 fixtures, each mutation-checked.

## Fleet state

- 23/23 instances advanced, capability gate GREEN, 0 tracked-dirty.
- `fractional-cxo` was the lone holdout: its launchd scanner writes TRACKED
  state files so it was permanently dirty. Fixed at its end (163b58c,
  gitignore + untrack), now updates normally.
- Ladder used before widening: school-negotiator (proved dry-run isolation),
  all_points_setup + Prodigy_Gold (the two the pathspec bug killed),
  Alice (3 gitlinks intact), then both parents (9 and 11 nested repos skipped,
  disk steady ~20Gi where the 2026-07-25 run died at 605MB).

## The line criterion (resolved, [USER-DIRECTED])

Original DONE required `wc -l < 1253` AND "no scar comment deleted" -- these
contradict, since `wc -l` counts the record the same line protects. It was NOT
met: 1253 -> 1485 (+232 = +186 comments, +46 code). Founder chose to restate it
on what the count was a proxy for. The PRD keeps the superseded criterion
visible rather than editing it away. sp-b4131535 resolved.

## Open threads

**Yours to decide:**
- `sp-64f800a4` - public repo publishes client-identifying files. Until this is
  settled, main stays 100 commits unpushed, which also means the plugin
  marketplace clone (HEAD 6a84604, 2026-07-04) cannot refresh -- that is the
  root cause of `sp-5a75214b`, the stale 0.1.0 prd-os cache whose runner is 161
  lines behind the skeleton and has no `spillover` subcommand at all.

**Deliberate deferrals, arguments already written:**
- `sp-72bd8029` - the config collision guard still lacks the byte-identical
  carve-out. Real fix, but a behaviour change, so it was out of a
  behaviour-preserving PRD. One call-site edit plus a fixture.
- `sp-7ff28101` - `managed_plugin_names` and `is_managed_plugin_path` disagree
  on dot-named plugin dirs. Pre-existing; the divergence moved rather than
  vanished.
- `sp-bd98a3f3` - the rebase-abort branch has a logic test, not an end-to-end
  fixture; forcing it needs `git rebase --abort` to fail.

**Tooling friction worth fixing:**
- `sp-59df4388` - 3 of 5 `bypass_check`s I wrote were grep-count proxies and
  each needed a mid-issue amendment; one actively caused a defect by forcing a
  dead call to satisfy a number. Assert the invariant, not a token count.
- `sp-a4f98f13` - destructive-op-deny matches heredoc bodies and grep patterns,
  so writing documentation *about* a destructive command is blocked. Fired 4x.
- `sp-31cd3a5c` - the DSSE scope hook blocks Write to the scratchpad outside
  the repo, forcing a bypass or a bash heredoc for analysis scaffolding.

## Notes for the next session

- The adversarial reviewer (fresh Claude subagent, must ship a runnable repro
  per finding) found **2 blockers I introduced**: restore deleting untracked
  files inside `memory/`/`output/`, and restore aborting a founder's own paused
  `rebase -i` in a linked worktree. Both now have permanent fixtures. That
  substitute reviewer is earning its cost -- keep using it while Codex is out.
- `gates run` is RED and expected to be: 13 open items from this run plus ~73
  pre-existing, which the plan said not to work.
- Reproducers and design notes live in the session scratchpad; the durable ones
  are the 4 new suite fixtures.
