# RCA: a filter added to one walker while the module's other walkers kept voting

**Date:** 2026-08-02
**Trigger:** Fable adversarial review of PR #74 flagged it as blocker B3; by then the same shape had already been fixed twice in the same file, and a fourth instance was found by codex INSIDE the commit written to eliminate the shape.
**Surface-fix commit:** 4b4dd3e (PR #74, six commits)
**Structural-fix commit:** pending — see Action items

## What happened

ASK-122 said 11 scripts in the Alice repo were unreferenced. Ten of them were
referenced; `capability-map-gen.py` scanned only `.claude/`, `plugins/` and
`q-system/` for wiring, and Alice's code lives in `q-investigate/` and `scripts/`.
A shell script containing `python3 "$G/fill_sheet.py"` was never opened.

Widening the scan fixed that and introduced the same shape again, four more times.
Each fix added a rule to one code path in a module that had several, and each time
the remaining paths kept voting with the old rule:

| # | The rule | Applied to | Missed | Found by |
|---|---|---|---|---|
| 1 | which dirs are wiring surfaces | 3 hardcoded subtrees | the rest of the repo | the issue itself |
| 2 | generated trees are not wiring | the surface walk | the engine walk (12 engines went dark) | Opus review, round 1 |
| 3 | `DATED_SNAPSHOT_RE` | the engine walk | `_iter_surface_files` (snapshots still wired) | Fable, B3 |
| 4 | `is_excluded_tree()` | 3 named consumers | a 4th: `has_test`'s own `rglob` | codex, round 4 |
| 5 | the invocation filter | `.md` files | `.txt` in `SURFACE_CODE_EXT` | codex, round 5 |
| 6 | "hidden dirs rank lower" | `.pr*rev/` scratch | also demoted `.claude/`, `.q-system/` | Fable, A1 |

Instance 4 is the diagnostic one: the commit consolidating everything behind one
predicate, whose message read *"one predicate for all three consumers"*, shipped
with a fourth consumer. The count was asserted, not enumerated.

## Surface symptom

`capability-map-gen.py` reported LIVE for dead scripts and UNWIRED for live ones,
in both directions, across five instances. Alice reported 22 local engines as
unreferenced when 19 had visible callers on disk.

## Surface root cause

Each individual miss is an ordinary omission: a second `rglob` that nobody
remembered, a filter applied at the point the defect was observed rather than at
every point the rule holds. Fixing each one is a two-line change, which is why
each was fixed and the next appeared.

## Structural root cause

type: implicit-contract

A module-level invariant ("this tree is not a wiring surface", "a dated snapshot
is not an engine") was expressed as a **conditional at each call site** rather
than as a chokepoint every walker must pass through. Nothing in the module could
answer "how many walkers are there?", so every fix was scoped to the walkers the
author happened to be looking at.

The count is the tell. Instance 4 shipped with a comment stating a specific number
of consumers, and that number was produced by memory rather than by a grep. A rule
whose coverage cannot be enumerated mechanically will be applied incompletely, and
the incompleteness is invisible because a walker that skips the filter does not
error — it just votes.

`fable-discipline` already names the fix ("single-writer chokepoint, guarded by a
grep-the-tree test") and `wiring-check.md` already names the gap class
("a cross-cutting invariant needs a written scope + a self-enumerating guard").
Both were loaded during this work. Neither is enforced by anything executable for
this file, so both were read and not applied.

## Verification

Each instance was confirmed by measurement against real repos, never by reading
the diff:

```
# instance 2 — measured, not inferred
old-vs-new per-capability diff across 5 instances
-> 12 engines under q-system/ became permanently dark in kipi-investigations

# instance 3 — Fable's repro, re-run here
DATED_SNAPSHOT_RE is NOT applied in _iter_surface_files
-> a rollback copy's `import geo_clues` keeps geo_clues.py LIVE

# instance 6 — measured
163 of 785 evidence witnesses cited .pr42rev/ scratch copies, not the real caller
```

Final state after all six fixes, run from `origin/main`:

```
test-capability-map-wiring.py    18/18 OK
Alice UNWIRED 44 -> 16 ; local actionable 21 -> 3
4_points 41 -> 24 ; investigations 47 -> 36 ; Pure_spectrum 22 -> 19
```

## Contributing factors

- **The unit tests could not see it.** All six instances are distribution
  properties across a real repo; a tempdir fixture with four files exhibits none
  of them. Every one surfaced from a population diff across five instances, or
  from a reviewer running on a different lab's weights.
  (See `rca-tests-that-pin-nothing-2026-08-02.md`.)
- **A false-LIVE is silent.** A false-UNWIRED produces a Linear issue and gets
  fixed. A false-LIVE produces nothing, so the error direction that hides is the
  one that accumulates.
- **Five review rounds each found the shape and none generalised it.** Reviewers
  report the instance in front of them; nothing asked "where else does this rule
  need to hold?"

## Fixes shipped

- Instances 1-6 individually fixed across PR #74 (`d20f412` → `6b38897`,
  merged as `4b4dd3e`).
- `is_excluded_tree()` consolidates the exclusion behind one predicate.
- Kill-tests added for the mutants that survived (Fable's mutation table).

## Action items

- [ ] Build `consumer-parity-check.py`: for a module declaring an exclusion
      predicate, **enumerate** every filesystem walker in it (`rglob`, `glob`,
      `walk`, `iterdir`) via AST and assert each routes through the predicate.
      Self-enumerating, so a new walker fails the check the day it is added
      rather than the day someone notices. Owner: Sana. Blocks: nothing.
- [ ] Wire it PostToolUse on edits to `capability-map-gen.py` and any module that
      declares a `*_EXCLUD*` / `*_SKIP*` / `is_*_tree` predicate. Owner: Sana.
- [ ] Add a negative self-test: remove the filter from one walker on a copy and
      prove the check goes red. A parity check that cannot fail is decoration.
      Owner: Sana.
- [ ] Retire the prose in `fable-discipline` SKILL.md §3 that claims the
      grep-the-tree test as a habit, and point it at the executable instead —
      prose that names no executable is what let six instances ship. Owner: Sana.

## Lessons

- A cross-cutting rule is a chokepoint plus a guard that enumerates its consumers,
  never a conditional repeated at the sites you can currently see.
- "One predicate for all three consumers" is a claim about a count. Counts in
  comments are produced by memory; run the grep and paste the number.
- When the same shape is found three times in one file, stop fixing instances.
  The third occurrence is evidence the class is unguarded, not that the author
  was unlucky.
