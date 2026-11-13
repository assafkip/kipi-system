# RCA: three review rounds on the founder-ask phone send each found a new failure in the same function

**Date:** 2026-11-12
**Trigger:** PR #778 (ASK-4728) returned REQUEST CHANGES three times; the review engine refuses a fourth round (cap 3).
**Surface-fix commit:** 503d06d6 (round 2 fix: 20 s send cap)
**Structural-fix commit:** pending

## What happened

The change makes a founder ask reach the phone through chief's gate, not only through the morning brief. The send was added inside `cap-ladder.py --founder-ask`, the recorder that other jobs call with a 60 s bound. Each review round found a different failure in that one send, and each fix added a rule to the same function instead of changing its shape.

## Surface symptom

Findings by round, read from the three review files under `~/.config/kipi/pr-reviews/` (pr-778, 144109, 145743, 151143):

- Round 1: the real message text was refused by chief's gate (census red); a failed send had no named consumer; the unsent read and the stamp sat in different lock scopes, so two runs could send the same ask twice.
- Round 2: the send sat inside a call both callers bound at exactly 60 s, and neither catches the timeout.
- Round 3: a verdict with `detail_saved` False was stamped as sent; the 20 s cap bounds `deliver()` but not the wait for the status lock; a sweep of N asks sends N phone messages.

## Surface root cause

`notify_new_asks()` runs inside `--founder-ask`, holds the status lock across `deliver()`, and stamps `notified_at` on `verdict["delivered"]` alone. Round 3 findings are lines 527 (stamp condition), 543 (lock held across the send) and 1162 (one send per process).

## Structural root cause
type: code-defect, missing-test, process

1. **One function is both recorder and sender.** `--founder-ask` must be fast and must never fail the caller; a send to another system is slow and can fail. Putting both in one process means every property of the send (lock, timeout, retry, batching, what counts as sent) becomes a property of the recorder's caller.
2. **A lock was held across a call to another system.** Round 1 widened the lock to cover read, send and stamp to stop a double send. That made the lock wait unbounded by any send cap, which is round 3 major 2. Round 2's cap bounded the call, not the wait for the lock.
3. **Each round fixed the named line, not the property.** Property: "an ask is recorded in bounded time, sent once per batch, and marked sent only when the founder can read it." Round 2 fixed the timeout, round 1 fixed the double send, and neither state the property as a test, so round 3 found the next hole in it.

Answer to the question asked: yes. Rounds 1, 2 and 3 each found a failure in `notify_new_asks()` called from `--founder-ask`. The census finding of round 1 is the content of the same send. Two of the three round-3 findings are caused by round 1 and round 2 fixes (the lock span, the 20 s cap).

## Verification

- Read all three review files; the round 3 reviewer states the same: "each round's fix created the next round's gap" and proposes claim, send outside the lock, stamp.
- Read `cap-ladder.py` at 503d06d6: `notify_new_asks` takes `_status_locked(go)` around `deliver()` (lines 516 to 543); the stamp tests `verdict.get("delivered")` only (line 527); `--founder-ask` calls it at line 1162.
- Read `founder_notify.py`: `deliver()` returns `detail_saved` when a detail was given (lines 288 to 289), so the field exists to be checked.
- Fix verification is in the PR: the test file `test_cap_ladder.py` case `case_founder_asks_reach_chief`, red before the fix and green after, with one mutant per decision point (Fixes shipped, below).

## Contributing factors

- The review loop was the design loop: the PR was reviewed three times without a stated property list for the send.
- Two callers bound the subprocess at 60 s with no handler, so any slowness in the recorder is a crash in the caller.
- The test fixture answered instantly, so no case held the lock for a slow send or recorded while a send hung.
- The notify fixture never emitted `detail_saved`, so a verdict without a saved detail could not be tested.

## Fixes shipped

- Round 1 (86cd2e21, 4db1965d): phone line names no ticket, asks travel as detail, nightly failure files to Sana, one lock.
- Round 2 (503d06d6): 20 s send cap.
- Structural fix: pending in the next commit on this branch.
  - `--founder-ask` records under the lock and returns; no call to chief.
  - `--send-asks` is the one sender; the nightly run calls the same function.
  - The status lock is held to read and to stamp, never across `deliver()`. A separate send lock serialises senders.
  - An ask is stamped only when chief reports delivered AND detail saved.
  - Both `--founder-ask` callers trigger one detached, bounded sender after their sweep.

## Action items

- [ ] Sana: split the recorder from the sender in `cap-ladder.py` (this PR).
- [ ] Sana: tests for the property, with the notify path stubbed: recording never sends; detail not saved leaves asks unsent; N asks then one send is one message; a hung chief does not fail a concurrent recorder; resolved asks are not sent.
- [ ] Sana: after merge, `cap-ladder.py --send-asks` sends the asks that are unsent now; the nightly `com.kipi.cap-ladder` run (04:40) retries any that fail.
- [ ] Sana: when a PR's fix adds a lock or a timeout around a call to another system, state the property list in the PR body before round 2.

## Lessons

- A recorder that also sends is two jobs. Split them, and the send's failure modes stop reaching the recorder's callers.
- Never hold a lock across a call to another system. Claim or read under the lock, release, call, take the lock again to stamp.
- "Sent" is what the receiving system says it holds, not that the call returned. Check every field of the verdict that says the payload landed.
- Two findings in one function in consecutive rounds is the signal to change the shape, not to patch a third time.
