# DoR: the dispatcher must notice when a selector it had is gone

> **Recovered work-product — a point-in-time snapshot, not current documentation.**
> This file existed only in a dirty checkout and was recovered on 2026-08-05
> (PR #106, ASK-363). Every claim about system state was true at this document's
> own date and may not be true now. In particular, "wired" here means *merged in
> this repository*; whether the RUNNING copy loads it is a separate question that
> `q-system/.q-system/scripts/runtime-plugin-freshness.py` answers, because the
> two came apart for a full day during this very build. Read it as a record of
> what was decided and why, and verify current state against the code.

## Problem

`kipi-dispatch.sh` runs from the working tree (`launchd` ProgramArguments point at
`/Users/assafkipnis/projects/kipi-system/kipi-dispatch.sh`, verified 2026-08-03).
So *which branch is checked out* decides what the 15-minute heartbeat can do.

During ASK-352 the reviewer-redrive selector drove the real loop from an unmerged
branch. Any branch switch in that checkout silently reverts the wiring mid-flight,
and the dispatcher keeps exiting 0 while doing strictly less than it did a minute
earlier.

Nothing detects this. The capability manifest checks declared-vs-actual per test
file; it does not ask whether the RUNNING dispatcher still has a call site it had
before. The failure is additive-loss, not corruption, which is exactly why it is
invisible: no error, no red gate, no page. The loop just quietly does less.

This is the same class as ASK-353's unresolved `tree-position-refused` state.

## Why it is not just "merge faster"

"We'll merge soon" is not a consumer. The window recurs on every agent branch, and
the checkout is shared between sessions (see the parallel-sessions scar). A guard is
cheap; noticing this by accident is not.

## Acceptance criteria

- [ ] The dispatcher records, at each run, which redrive selectors it resolved
      (path exists AND is referenced from a live call site), into a state file
      written through a single writer.
- [ ] On a run where a selector that was present on the previous run is now
      absent, it pages ONCE via `slack-notify.sh`, naming the selector and the
      current branch/HEAD. It does not page again while the state is unchanged.
- [ ] Recovery is reported too: the selector coming back pages once. An operator
      who never hears the recovery cannot tell a degraded loop from a healthy one
      (same posture as `note_degraded_transition` in `pr-review-agent.sh`).
- [ ] A reproducer drives the REAL `kipi-dispatch.sh` with a selector removed
      between two runs and asserts exactly one page, read off the notify stub's
      own record, never off stderr.
- [ ] Mutation check: deleting the page call makes a case go red; making it page
      every run makes a different case go red.
- [ ] The test never touches the real `slack-notify.sh`.

## Allowed files

- `kipi-dispatch.sh`
- `q-system/.q-system/scripts/test/test-dispatch-capability-drift.sh` (new)
- `q-system/.q-system/capability-manifest.json`

## Out of scope

- Changing where the dispatcher runs from (repo-root vs a pinned checkout). That is
  a bigger call and belongs with ASK-353's `tree-position-refused`.
- Any change to `review-redrive.py` or `ci-redrive.py` themselves.
