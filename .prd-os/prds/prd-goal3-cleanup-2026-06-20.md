---
id: prd-goal3-cleanup-2026-06-20
title: Goal3 Cleanup
status: archived
created_at: 2026-06-20T02:22:06Z
updated_at: 2026-06-20T02:28:23Z
owner: assafkip
reviewers: []
findings_path: .prd-os/findings/prd-goal3-cleanup-2026-06-20-findings.jsonl
codex_reviewed_at: 2026-06-20T02:23:32Z
---

# Goal3 Cleanup

## Problem

The Goal-3 wiring audit found one real defect left behind by the Goal-2
auto-update-nudge change. `q-system/hooks/auto-update.sh` still carries a
dirty-working-tree skip block (lines ~57-62) that predates the nudge-only
rewrite. Back when the hook ran `git subtree pull`, skipping on a dirty tree
was correct (do not pull over uncommitted work). The hook no longer pulls --
it only prints a one-line "an update is available, run: kipi update" nudge and
never touches files. The leftover skip now suppresses that harmless nudge for
any founder who has uncommitted work, which is most of the time. Observed: a
founder with a dirty tree never sees the update nudge at SessionStart, so the
feature silently does nothing for them. The existing test only exercises a
clean tree, so the gap is untested.

## Goals

- The SessionStart update nudge fires regardless of working-tree state (clean or dirty), since it only prints a message and never mutates files.
- A test proves the nudge fires on a DIRTY tree (the path the current test misses).

## Non-goals

- No change to nudge content, cadence, the sentinel/throttle logic, or the `kipi update` path itself.
- No deletion of the untracked output/ scratch files (captoken-*/cc-spex-*) -- that is a founder cleanup decision, tracked separately, not in this PRD.
- No re-introduction of any auto-pull behavior.

## Proposed approach

Delete the dirty-tree skip block in `auto-update.sh` so control flows straight
to the nudge regardless of `git status` cleanliness. Keep the once-per-window
sentinel throttle (that is about frequency, not tree state). Add a dirty-tree
case to `test-auto-update-nudge.sh`: stage an uncommitted change in a temp repo
fixture, run the hook, assert the nudge string is emitted and exit 0.

## Risks and rollback

Blast radius: one SessionStart hook that only prints. Worst case if wrong: the
nudge prints too often (still harmless, throttled by the sentinel) or not at
all (same as today's broken state). Rollback: `git revert` the single commit.
No data path, no migration, no mutation.

## Open questions

- None. Scope is one dead branch + one test case.

## Issues

```json
[
  {
    "id": "auto-update-nudge-dirty-tree",
    "title": "auto-update nudge fires on a dirty tree (remove dead pull-era skip)",
    "priority": "p2",
    "finding_id": "finding-1",
    "allowed_files": [
      "q-system/hooks/auto-update.sh",
      "q-system/.q-system/scripts/test/test-auto-update-nudge.sh"
    ],
    "required_checks": [
      "bash q-system/.q-system/scripts/test/test-auto-update-nudge.sh"
    ],
    "bypass_check": "bash q-system/.q-system/scripts/test/test-auto-update-nudge.sh",
    "acceptance": "Delete the dirty-tree skip block (lines 57-62) in full, including its in-block sentinel touch; nudge emits regardless of working-tree state; test asserts nudge fires on a dirty fixture and exits 0; sentinel throttle preserved; no auto-pull reintroduced."
  }
]
```
