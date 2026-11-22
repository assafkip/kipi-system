# RCA: PR 866 (refuse a reopened capped PR) needed three fix rounds and was still REQUEST CHANGES

**Date:** 2026-11-21
**Trigger:** round 3 delta review of PR 866 returned REQUEST CHANGES at head e3e5ea78; the three-round cap was reached
**Surface-fix commit:** e3e5ea78
**Structural-fix commit:** pending

## What happened

ASK-5485 adds a check to pr-review-agent.sh that refuses a PR which reopens a capped PR. The check must still let through the successor that cap-ladder.py itself opens. Each review round found a new hole in how the reviewer recognises that successor. Three fix rounds closed three holes and the third review found a fourth.

## Surface symptom

Review verdicts on PR 866, all REQUEST CHANGES:
- Round 1 (head 555b0c10): the allowance read the ladder state file, which is written once at the end of a nightly run and never records release() successors.
- Round 2 (head 1edc1a21): the allowance read a Resumes #N prefix, which only climb() writes and which names only the latest predecessor.
- Round 3 (head e3e5ea78): the allowance now reads a Ladder-successor tag on line one of the body, but a single failed gh pr view body read is treated as no proof, so the ladder's own successor is refused and marked capped.

## Surface root cause

Each round keyed the allowance on a different signal the successor might carry, and each signal was read through a different failure mode: a state file written late, a prefix written by one of two callers, a network read with no unknown state.

## Structural root cause

### Root cause #1
type: implicit-contract

The check answers two questions at once: is this PR a reopen, and is it the ladder's own successor. The second answer has no single recorded source of truth. cap-ladder.py has two callers of open_from_branch (climb and release) and the reviewer was written against what the first caller left behind, without reading the second.

### Root cause #2
type: process

Three rounds of the same finding class (the allowance signal is fragile) were each fixed at the signal, not at the shape of the decision. The reviewer states the shape in round 3: a failed read must mean unknown, never refuse, the same standard the status read in the same file already follows with READ_OK.

### Root cause #3
type: missing-test

No test drives a failed gh read through the reopen path. The tests build fixtures that always return a body, so the unknown state was never exercised.

## Verification

Ran test-review-reopen-refused.sh at e3e5ea78: PASS (10 checks). Ran one mutant (allowance case line deleted): the test went red with PR 6 refused. Ran test-review-round-cap.sh: PASS (12 checks). These prove the reviewed behaviour holds. They do not cover the round 3 major, which is why the PR is not merged.

## Contributing factors

- The ladder state file is written once per nightly run, after up to five caps of work.
- release() and climb() build their successor bodies separately.
- A refusal writes a .round-cap marker, which the ladder reads as a review cap on the next night, so a wrong refusal costs a ladder rung.
- Rounds 2 and 3 changed the accepted signal without changing the unknown-state handling, so the same class came back.

## Fixes shipped

- Surface fix: tag on line one of every ladder successor body, written in open_from_branch (cap-ladder.py), read from line one by the reviewer, e3e5ea78.
- Structural fix: pending. Capture the exit status of the body read at pr-review-agent.sh line 500. A failed read is unknown: do not set REOPEN_OF, do not write the marker, warn on stderr, mirroring READ_OK for the status read.

## Recurrence

<!-- rca-recurrence-skip -->

## Action items

- [ ] Treat a failed body read as unknown in the reopen check, with a test whose gh stub fails the body read — owner: Sana fresh agent on PR 866 — type: code
- [ ] Make the legacy Resumes #N glob number-aware or drop it, and restore a test that pins it — owner: Sana fresh agent on PR 866 — type: test
- [ ] Pin the 140 character status truncation with a test and keep the override text inside it — owner: Sana fresh agent on PR 866 — type: test
- [ ] Correct the PR description check count from 5 to 10 — owner: Sana fresh agent on PR 866 — type: doc
- [ ] Capture the hosted reviewer gap, already filed as ASK-5534 (sp-0e6a14ec) — owner: Sana worker picks ASK-5534 — type: process

## Lessons

- A reviewer finding that returns in a new form after a fix is about the decision shape, not the signal. Fix the unknown-state handling first.
- Two callers of one producer means the consumer must be tested against both.
- A read that can fail needs three outcomes in the code and in the test: yes, no, unknown.
