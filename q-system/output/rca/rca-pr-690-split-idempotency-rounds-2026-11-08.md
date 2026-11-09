# RCA: PR #690 took three review rounds because each fix guarded one branch of SPLIT, not the invariant

**Date:** 2026-11-08
**Trigger:** iteration-speed rule 6 and the lane's stop rule: 3 review rounds without approval on kipi-system PR #690 (ASK-3959 stage 2). The sana-route lane stops here and starts no round 4.
**Surface-fix commit:** ca5ebd41 (round 2 fix; round 3 findings still open)
**Structural-fix commit:** none yet. ASK-4133 owns it.

## What happened

PR #690 adds `linear-route-decide.py`. It gives a ticket no rule can route one validated decision: ROUTE, CLOSE or SPLIT. SPLIT is the only decision that files permanent Linear issues. Every round found a major in that one place.

- Round 1 (`pr-690-20261108-175724.md`), finding 2: when the children landed and the record comment failed, the next night filed a second set.
  - Fix a33e07b4: a marker on each child, and reuse by exact title.
- Round 2 (`pr-690-20261108-181055.md`), finding 1: a reworded answer on night 2 still filed a second set.
  - Fix ca5ebd41: any marked child means the split is done, and the run resumes with no model call.
- Round 3 (`pr-690-20261108-182253.md`), finding 1: the resume ignores the children's state. A parent that was reopened on purpose, with its children canceled, is re-canceled every night.

## Surface symptom

Round 3 reproducer, from the review: after a clean split, the record's own undo (reopen the parent, cancel the children) is reverted on night 2 and again on night 3. The ticket then holds 3 records and 0 live children.

## Surface root cause

`resume_decision()` at ca5ebd41 returns a resume whenever `issue["split_children"]` is non-empty. `CHILDREN_QUERY` reads `identifier title description project{name}` and no `state`, so a canceled child counts the same as a live one.

## Structural root cause

### Root cause #1
type: code-defect

The invariant was never written down as one read. The invariant: "this parent's split is the set of its live marked children, and every decision on the parent consults it." Each round added a condition to the branch the finding named:

- round 1 added the record path;
- round 2 added the title and resume paths;
- round 3 found that the resume path had no state, and that ROUTE never reads the children at all (finding 3).

A guard that lives in one branch of `apply_decision` cannot hold for the others. So each fix moved the hole instead of closing it.

### Root cause #2
type: process

SPLIT went into v1 at full scope before anyone measured how often it is chosen. It is the only decision that makes permanent objects through a write sequence that is not atomic. Measured on 3 live report-only decisions (ASK-313 twice, ASK-368): all were ROUTE. So the highest-risk branch carried most of the review cost and may be the least-used one. Recon measured the creation stamp before building it, which is why that part needed no code. SPLIT got no such measurement.

### Root cause #3
type: missing-test

Every SPLIT test proved one night, or two nights with no change in between. No test ran the state machine across nights while the parent and the children were edited in between (reopen, cancel, project change). The reviewer found each defect by writing exactly that sequence by hand.

## Verification

- Round 1 case, red first at 374c9546: `test_a_split_whose_record_failed_files_no_second_set_of_children` gave `assert 4 == 2`. Green at a33e07b4.
- Round 2 case, red first at a33e07b4: the same test with reworded titles gave `['a', 'c', 'a, reworded', 'c, reworded']`, `assert 4 == 2`. Green at ca5ebd41.
- Round 3 case: the reviewer's reproducer at ca5ebd41 shows `their real board state: ['canceled', 'canceled']`, `model asked? NO`, and `parent state after: canceled` on nights 2 and 3. `grep -n CHILDREN_QUERY -A1 q-system/.q-system/scripts/linear-route-decide.py` shows no `state` field.
- Mutation at ca5ebd41: 14 of 14 mutants are killed by named tests (`mutate_3959.py` in the lane's scratchpad). Every guard that exists is tested. The missing guard is the defect.

## Contributing factors

- Delta reviews are right on cost. But each delta added a new branch, and the reviewer attacked the new branch, so every round found something new in code the round before had added.
- The founder ruling (no park, no timed retry) rules out the easy answer, "leave a split ticket alone until a human looks". So the idempotency has to be exact.

## Fixes shipped

- Surface fix: round 1 and round 2 duplicate paths closed (a33e07b4, ca5ebd41), pinned by tests and mutants.
- Structural fix: not shipped. ASK-4133 holds the design: one state-aware `split_state()` read that every branch consults, or remove the creates from v1 after measuring how often SPLIT is chosen.

## Action items

- [ ] Measure SPLIT frequency with a 20-ticket report-only run, then build ASK-4133 on the chosen shape. Run the next review with KIPI_REVIEW_MAX_ROUNDS=4 and a PR comment that says why. — owner: the fresh Sana agent the orchestrator starts on ASK-4133 after this lane's report — type: code
- [ ] Add a multi-night state test: split, then a failed record, then a reopen and a cancel of the children, then nights 2 and 3. Assert no duplicate child and no re-cancel of a reopened parent. — owner: the same agent, inside ASK-4133 — type: test
- [ ] Do not install com.kipi.linear-route-decide until #690 merges. It is not installed now, so the round 3 defect cannot run. — owner: the agent that merges #690 installs it from a fresh origin/main tree — type: process

## Lessons

- A guard for a permanent write must be one read that every branch consults. A condition added to the branch a finding names moves the hole.
- Measure how often a decision is chosen before you build its riskiest branch at full scope.
- Test a state machine across nights with edits in between. One-night tests prove one-night code.
