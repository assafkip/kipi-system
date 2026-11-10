# RCA: PR #712 (ASK-4306) reached the 3-round review cap and round 3 still found a new major on lines rounds 1 and 2 had read

**Date:** 2026-11-09
**Trigger:** round-3 review of PR #712 at head 83c9642f, verdict REQUEST CHANGES. Reviews: `~/.config/kipi/pr-reviews/assafkip_kipi-system__pr-712-20261109-{162013,165200,170134}.md`
**Surface-fix commit:** this branch, round-4 commit (ASK-4306)
**Structural-fix commit:** same commit (`_queue_consumer`, `wait-guard.sh`)

## What happened

PR #712 adds `wait-has-consumer.py` and `lane-mark.py hold`: a wait must name a consumer, checked in code (RULE-2026-11-09-B). Each round found a different major:
- Round 1: `local_projects()` counted 14 checkouts where the dispatcher enters 3; the new test ran in no CI job; nothing calls `hold`.
- Round 2: `hold` wrote back a stale marker and erased a concurrent `end`; an unreadable marker read as a live consumer.
- Round 3: the no-DoR and `needs-scope` refusals say "nothing picks this up" for tickets `linear-dor-drafter.py` drafts at 03:00; the PR arm lets a lane hold on its own PR; nothing calls `hold` (third time).

## Surface symptom

Round 3, finding 1, repro with both modules loaded and Linear faked:

```
ASK-7001 owner:sana, project, no DoR   check: ok=False (blames missing DoR)   selection_mode: draft
ASK-7002 owner:sana, needs-scope       check: ok=False (blames the label)     selection_mode: redraft
```

Finding 2: `consumer_for` passes `waiter` to the ticket arm and drops it for the PR arm. Finding 3: a grep for `holds` returns only the writer and the test file.

## Surface root cause

`wait-has-consumer.py` `_why_not` (lines 184, 191): two refusal strings are written as facts about the world ("the worker does not pick it") when the question is "will any scheduled job act on it". The PR arm (`_consumer_for_pr`) never received `waiter`.

## Structural root cause

### Root cause #1: the consumer list was built from one actor, not from the fleet

type: process

The check asks "would linear-worker.sh pick it" and treats a no as "nobody". The fleet has at least four jobs that act on a ticket or PR: the worker, `com.kipi.linear-dor` (03:00, 8 a night), `com.kipi.linear-alert-triage` (60 a night) and `pr-owner.py` (hourly). The PR that enforces "name a consumer" never enumerated the consumers. Measured on 83c9642f:

```
$ grep -c 'linear-dor-drafter\|linear-alert-triage' q-system/.q-system/scripts/wait-has-consumer.py
0
```

Each round then found the consumer the previous round had not listed, because each review read the diff, and the diff only held the actors its author had thought of. The round-3 reviewer says the same: "enumerate every scheduled job that acts on a Linear ticket, then ask the refusal text whether it holds for each".

### Root cause #2: "has a consumer" had no time bound

type: implicit-contract

A nightly job that takes 8 of 1,094 tickets is a consumer for 8 tickets. The spillover scar (ASK-4195) is exactly a ticket behind such a cap. Without a 24-hour bound the check cannot tell a drafter that will act from one that will not act this month, so the first correction (add the drafter) would reopen the original scar. The rule needs "inside the cap" in code, with the cap read from the job's plist.

### Root cause #3: the check shipped with no caller

type: code-defect

Rounds 1, 2 and 3 all raised "nothing calls `hold`" (nonblocking). It was deferred each time as a wiring question for the orchestrator. The watchers that wait are shell scripts, and the only entry point was a Python subcommand of a lane tool. A gate with no caller is the defect the PR was written to remove, one layer up.

### Root cause #4: the self-reference fix was applied to one arm

type: process

Round 1's minor "a lane may hold on itself" was fixed in the ticket arm. The PR arm is a second code path for the same class. Same shape as `rca-capability-expiry-round-3-2026-11-09.md` root cause #1: the fix covered the site shown.

## Verification

- Round 3 reproduced findings 1 and 2 at 83c9642f (review file above).
- Before this fix: `test_wait_has_consumer.py` 32 passed at 83c9642f, none covering a queued consumer or a PR self-wait.
- Fixed: 43 passed. Mutants: setting the cap check to `cap + 10000` turned 2 tests red (behind-cap drafter, behind-cap alert); skipping the PR self-check turned 1 red. Restored, 43 passed.
- `wait-guard.sh` is tested against a stub check in a temp dir (exit 0, 1, 2 pass through) and against the real check for a typo (64).

## Contributing factors

- Each fix brief named the finding's line, so the fix stayed on that line.
- Rounds 1 and 2 read `_why_not` and did not ask whether each refusal string was true for every other job.
- The caller question was marked nonblocking three times, so no round forced it.

## Fixes shipped

- Surface: `_queue_consumer` counts the drafter and the alert triage as consumers only while the ticket is inside the nightly cap; `_consumer_for_pr` refuses the PR the waiting lane drives.
- Structural: queue order and caps come from the jobs' own code (`prioritise`, `fetch_draftable`, `lane_pools`) and plists, not copies; `wait-guard.sh <blocker> [waiter]` is the first caller.

## Action items

- [x] Count `linear-dor-drafter.py` and `linear-alert-triage.py` as consumers only inside their nightly cap (24h bound); owner: fresh Sana agent (ASK-4306); type: code
- [x] Refuse a wait on the PR the lane itself drives; owner: same agent (ASK-4306); type: code
- [x] Add `wait-guard.sh` as the first caller, pinned by one test; owner: same agent (ASK-4306); type: code
- [ ] Orchestrator watcher scripts call `wait-guard.sh <blocker> <lane ticket>` and stop on non-zero before they wait; owner: orchestrator after merge (ASK-4306); type: process
- [ ] Before fixing a consumer finding, list every scheduled job that acts on the object and test the refusal text against each; owner: every Sana lane (ASK-4306); type: process

## Lessons

- "Name a consumer" is a census of actors. Enumerate them before writing the first refusal.
- A consumer that acts on a fraction of a queue is a consumer for that fraction only. Put the bound in code.
- A check with no caller is a draft. Ship the first caller in the same PR.
