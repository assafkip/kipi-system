# RCA: the WIP ceiling stops the fleet worker on PRs no worker round can move (2026-11-07)

Founder ruling, verbatim, 2026-11-07: "I want Sana to tell me if removing the 5 pr limit would help this. this is something that is a real problem. i want sana to diagnose this. We cant have things be totally stuck with no recourse"

Acceptance bar taken from the last sentence: the fleet worker never reaches a state where it is fully stuck and nothing automated can get it out.

**Date:** 2026-11-07
**Trigger:** founder observation; `kipi work` (dry) at 20:53Z showed the ceiling held at 9 open own PRs with 1 movable.

Diagnosis only. No code, PR, ticket or Linear state was changed. Author: Sana. Measured 2026-11-07 20:53Z to 21:15Z at origin/main d65ac5d5. `linear-worker.sh` is byte-identical to 19a6cb2d (#627 touched other files).

## Short answer

- Removing or raising the limit does not fix this. Removing it brings back the silent pile the ceiling was built to stop. Any fixed number deadlocks again, because an unmovable PR has no exit: no line of tracked code closes a PR.
- Root cause: the ceiling was ported from chief without chief's drain. Chief pairs `WIP_CAP = 5` with LGTM's stale close. kipi-system got the stop and wrote the exit as a ticket name, not code.
- Fix: every tick either works an issue, reworks a movable PR, or releases one unmovable PR through a coded exit. The "Starting nothing" branch becomes unreachable.

## What happened

- 2026-09-30: chief adds `WIP_CAP = 5` after 82 open `sana/*` PRs (`~/projects/chief/chief/cloud_worker.py:75`). Chief already drained: LGTM closes a PR idle 14 days, branch kept, issue back to the queue, at most 25 a day (`~/projects/chief/bots/lgtm/skills/__init__.py:74-92`).
- 2026-11-06: RULE-2026-11-06-B. ASK-3826 ports the cap to `linear-worker.sh`. PR #613, squash 27986edf.
- 2026-11-06 23:49Z: #613 review round 2 names this exact failure as a nonblocking major: "when the ceiling holds and no candidate can move, the worker starts nothing on every tick indefinitely and pages nobody (linear-worker.sh:2037)". Captured as spillover sp-55e61d4b and auto-filed as ASK-3866. ASK-3866 carries `needs-triage` and an alert fingerprint, so `ready()` rejects it (`linear-worker.sh:787`). Its consumer is the needs-triage promoter, which wrote 0 decisions in 15 passes (RULE-2026-11-06-B reason). The promoter's fix is #606, one of the parked PRs.
- 2026-11-06 to 11-07: the supervised structural-fix program merges 10 PRs and stops 5 at the review limit (#606, #609, #614, #618, #621). All 5 stay open on lane branches.
- 2026-11-07 21:05:55Z: `kipi work --limit 9` (dry, so every PR is judged): 9 open own PRs, 1 movable.

## Surface symptom

`kipi work` prints "WIP ceiling: 9 open own PRs in assafkip/kipi-system (ceiling 5). No new issue starts". 215 ready issues wait. The only pick is #560. Once #560 merges or caps, every tick prints "Starting nothing" (`linear-worker.sh:2037`), pages no one, and does nothing.

## Surface root cause

8 of the 9 open `sana/` PRs cannot be moved by a worker round, and 8 >= 5. The orchestrator's hypothesis holds, with one correction: #584 is held because its ticket ASK-3574 is Done, not for its round cap.

Measured with the worker's own classifier (`kipi work --limit 9`, dry, 21:05:55Z), plus `gh pr view` and the verdict records in `~/.config/kipi/pr-reviews`:

| PR | Ticket (state) | Branch | Rounds | Last verdict | Verdict at current head? | Merge state | Auto-merge | Worker says |
|---|---|---|---|---|---|---|---|---|
| #543 | ASK-2810 (In Progress) | worker | 3 | APPROVE | yes | DIRTY | on | at the review round cap |
| #559 | ASK-2058 (In Progress, needs-triage) | worker | 3 | REQUEST CHANGES | no | BLOCKED | on | ticket is a fleet alert |
| #560 | ASK-3064 (Backlog) | worker | 1 | APPROVE WITH NITS | no (drift) | DIRTY, validate red | on | movable: picked |
| #584 | ASK-3574 (Done 11-01) | worker | 3 | APPROVE | no (e3cf78b8 vs 69c0f8c2) | BLOCKED | on | ticket is Done |
| #606 | ASK-3823 (Backlog) | lane | 3 | REQUEST CHANGES | yes | BLOCKED | off | lane branch |
| #609 | ASK-3821 (Backlog) | lane | 3 | APPROVE WITH NITS | yes | BLOCKED, validate red | off | lane branch |
| #614 | ASK-3827 (Backlog) | lane | 3 | REQUEST CHANGES | yes | DIRTY | off | lane branch |
| #618 | ASK-3830 (Backlog) | lane | 2 | REQUEST CHANGES | yes | DIRTY | off | lane branch |
| #621 | ASK-3829 (Backlog) | lane | 2 | REQUEST CHANGES | yes | DIRTY | off | lane branch |

Required checks on main: `validate`, `kipi/reviewer-approved`, `verify` (`gh api .../branches/main/protection`).

#560 cannot end the stop either way. If it merges, 8 unmovable remain. If its next rounds fail, it caps and 9 remain.

## Structural root cause

type: implicit-contract

The ceiling assumed every open PR it counts has a consumer that will move it out. Nothing in code makes that true.

1. **A stop with no exit.** Chief's pattern is a pair: the cap stops new starts, LGTM drains what cannot move. ASK-3826 ported the stop (`linear-worker.sh:985`) and wrote the exit as a sentence ("whose consumer is ASK-3824", `:2037`). Zero tracked code closes a PR: `git grep -n "gh pr close"` over the tracked tree, minus `.md`, returns nothing. 28 `sana/` PRs were closed unmerged since 2026-10-01, every one by hand.
2. **Every cap ends in "page and keep the PR open".** The reviewer cap (`pr-review-agent.sh:398-430`), attempts (`linear-worker.sh:2066-2112`), rebase rounds (`:2303`) and drift rounds (`:2280`) each page or file a ticket and leave the PR open. The WIP ceiling is the first code that reads the open set as a whole, so it is where the leak turns from a slow pile into a hard stop.
3. **The warning went into a queue nobody reads.** sp-55e61d4b predicted this, was marked nonblocking, and became ASK-3866 in the needs-triage queue: the worker cannot pick it, and that queue's consumer is broken. The fix for the consumer is #606, which is itself parked. That is a closed circle.
4. **Supervised lanes have no end-of-run exit.** Lane branches (`sana/<id>-<slug>`) cannot be reworked by the worker (`linear-worker.sh:993-999`, `:1087-1088`). The worker finds an existing PR only by `--head sana/<id>` (`:2160`). Lanes are never armed for auto-merge, because only the worker arms its own PRs (`:1725-1753`). The program ended with 5 lanes open, and each one counts toward the ceiling.

## Q1. Would removing or raising the 5-PR limit help?

**No.** Removing it unblocks starts and brings back a pile that only grows. Raising it delays the same stop by a few days.

What removing it unblocks:
- 215 ready issues. One start per tick (`LIMIT=1`, `linear-worker.sh:235`), one tick every 900s, daily cap 10 new issues (ASK-3826).

What it brings back (RULE-2026-11-06-B, "PRs that just hang there and die"):
- Unmovable PRs only arrive. Arrivals: 24 review-cap tickets in the 35 days before 11-06, about 0.7 a day, plus 9 "stuck after 3 attempts" tickets (RULE-2026-11-06-B reason). Exits: 0 in code.
- Worker outflow is small. In the 14 days since 10-24, 5 worker-branch PRs (`sana/ask-N`) merged, about 0.36 a day. The other 36 `sana/` merges were supervised lanes.
- Little's law: open PRs = arrival rate x time in system. For an unmovable PR the time in system has no bound, so the open count has none. That is chief's 82 and kipi-system's 17 open PRs on 2026-11-06.
- Age shows the same thing. Merged `sana/` PRs since 10-24 had a cycle time of p50 0.05 days, p85 0.17 days, max 2.99 days. Every open worker PR is 7 to 16 days old. In this sample, no PR older than 3 days ever merged. These are not work in progress. They are inventory with no exit.
- A side effect today: the 5 lane tickets are Backlog, owner:sana, with a DoR. `ready()` (`linear-worker.sh:760-794`) never checks a Backlog ticket for open PRs, so they are pickable. Picking one runs into the dispatch branch guard ("skip ASK-N: its open PR is on sana/ask-N-slug", `kipi-dispatch.sh:1379`), which is the ASK-2058 stall class: 442 and 323 repeated turns in Aug and Sep.

Raising it to N:
- The stop returns when the unmovable count reaches N. Today that count is 8. It came from 3 worker PRs over 9 days plus 5 lanes from one supervised day. A ceiling of 10 buys about one more supervised day or 3 worker days.

A version that keeps the purpose:
- Counting only movable PRs ends the stop at once (1 movable today, under 5). Alone, it turns the 8 into an uncounted pile with no consumer, which is the state RULE-2026-11-06-B forbids.
- **Decision:** keep 5 and keep counting every own PR. Add the exit (Q3). With the exit, the count holds only for as long as release takes, one PR per tick.

## Q2. Every state with no automated consumer

"Counts" means the PR counts toward the ceiling (`own` is every `sana/` head branch, `linear-worker.sh:1076-1081`).

| # | State | Where it parks | Consumer | Counts |
|---|---|---|---|---|
| 1 | Review round cap (3 usable rounds) | `pr-review-agent.sh:398-430` refuses before the model call and files a needs-triage ticket; worker `wip_move_why` `linear-worker.sh:1940-1946` | Ticketed: ASK-3824 (Backlog, blocked by ASK-3833). Even when landed it ends in one page with the PR still open. | yes |
| 2 | Lane branch `sana/<id>-<slug>` | `linear-worker.sh:993-999`, `:1087-1088`; existing PR lookup is `--head sana/<id>` only, `:2160`; dispatch branch guard `kipi-dispatch.sh:1379` | Missing on main. #560 has the adoption repair, but it fires only on `skip ASK-N:` lines (measured below), which the ceiling never writes. | yes |
| 3 | Lane approved and green, auto-merge off | the worker arms only its own PRs, `linear-worker.sh:1725-1753` | Missing | yes |
| 4 | Approved at head, required check red | `rework_gate` `pr-verdict-lib.sh:716` returns 10 for APPROVE + BLOCKED, read as "nothing to rework" | `ci-redrive.py` (ASK-295) for worker branches; missing for lanes (branch guard) | yes |
| 5 | Approved at an old head (drift) and at the cap | gate 40, but the cap check (`:1940`) comes first; the reviewer refuses at the cap | Missing | yes |
| 6 | Approved at head, conflicting, at the cap | a rebase makes a new head, the new head needs a review, and the review refuses at the cap | Missing | yes |
| 7 | Ticket is a fleet alert | `refusal_why` `linear-worker.sh:1029`; `ready()` `:787` | `linear-alert-triage.py`: 0 decisions in 15 passes; its fix is #606, parked | yes |
| 8 | Ticket Done or Canceled, PR open | `refusal_why` `:1033` | Missing | yes |
| 9 | Ticket not on the board | `rework_hold` `:1047` | Missing | yes |
| 10 | Ticket labelled needs-scope, blocked:capability or owner:assaf, PR open | `refusal_why` `:1023` | The label has a consumer (DoR drafter, capability grant, error page). The PR has none. | yes |
| 11 | Attempts spent (3 of 3) | loop `:2066-2112` skips "TERMINAL", pages once, requeues; `wip_move_why` `:1928-1930` | Ticketed: ASK-3824. The PR stays open. | yes |
| 12 | Rebase rounds spent (2) | `:1966-1967`; page at `:2303` says "needs a human" | Ticketed: ASK-3824 | yes |
| 13 | Drift rounds spent (2) | `:1968-1969`; page at `:2280` says "needs a human" | Ticketed: ASK-3824 | yes |
| 14 | Codex hold | `:1931-1935` | Exists and is bounded: released when Codex answers or the claim is a day old (`CODEX_OUTAGE_MAX_AGE=86400`, `:121`) | yes, at most a day |
| 15 | Waiting on a first review | gate 20 | Exists: reviewer redrive. It ends in row 1 if rounds run out. | yes |
| 16 | Past the walk bound (more than 10 candidates) | `:1089-1090` | Transient while the list is long | yes |
| 17 | PR count unknown (gh down) | `:1983-1997`, starts nothing | External, paged once per outage | n/a |
| 18 | **Ceiling held, zero movable** | `:2036-2038` prints "Starting nothing", no page, no action | Missing. ASK-3866 exists but the worker cannot pick it (alert label, no DoR). | the stop itself |
| 19 | Age gate (#626) | `issue_runner.py:498`, inside `cmd_load`, the verb `/issue-start` runs | Not a second lock on the worker. `linear-worker.sh` never calls `issue_runner`, and the kipi-dsse scope hook allows edits when no issue is active (`scope_hook.py:6`). No `.prd-os` spec names ASK-3824, ASK-3833 or ASK-3826, so it does not block the fix either. It refuses 21 of 77 kipi-system specs for supervised starts, with a logged `--age-override`. | no |

Today's 8 unmovable PRs, by row: #543 rows 1 and 6; #559 rows 1 and 7; #584 rows 1, 5 and 8; #606 and #614 rows 1 and 2; #609 rows 1, 2 and 4; #618 and #621 row 2.

## Q3. The structural fix

**Decision (Sana):** keep `WIP_CEILING = 5` and its count. Add a release step. Make "Starting nothing" unreachable except for an external outage that pages.

**The invariant.** Every worker tick at a repo does one of four things:
1. works an issue;
2. reworks a movable PR;
3. releases one unmovable PR through a coded exit;
4. names an external outage that pages once and has an expiry.

The release runs on every tick at or above the ceiling, one PR per tick, oldest first, alongside the rework.

**Where.**
- `q-system/.q-system/scripts/linear-worker.sh`: new `wip_release <pr> <issue> <kind>` beside `wip_move_why` (`:1926`). The WIP block (`:2005-2040`) calls it for the oldest passed-over PR. The no-movable branch at `:2036` calls it instead of only printing.
- The picker half (`:1083-1093`) emits the hold kind as a machine key (lane, alert, ticket-closed, not-on-board, refused-label, walk) next to the prose. The release then keys on kinds, not on prose prefixes like `case "lane branch"*`.
- The kind-to-exit table goes in `q-system/.q-system/terminal-states.json`, read by `wip_release`. That is one table with one reader, and it is where RULE-2026-11-06-A already requires every terminal state to name a consumer on main.

**Exits by kind.**
- Lane under the cap: adopt it. Push the lane head to `sana/<id>` as a create-only ref, open the replacement PR, close the lane PR with a link, keep the branch. Reuse `repair_branch_guard` from #560 (`dispatch-stall-check.py:211`) as a shared helper. Carry the round count to the replacement, so adoption never resets the review cap.
- Cap, rebase rounds, drift rounds, attempts spent (lane or worker): until ASK-3824 lands, close the PR with the last FINDINGS block in the comment, keep the branch, and return the ticket to Backlog through `requeue_issue` (`:1871`) with "resume from branch X at sha Y". Charge one attempt. At 3 attempts the ticket gets needs-scope, whose consumer is the DoR drafter. Once ASK-3824 lands, it takes over these kinds, and its last step (after the page) still closes the PR.
- Ticket Done, Canceled or not on the board: close the PR, keep the branch, comment on the ticket. No requeue.
- Alert ticket or refusal label: close the PR, keep the branch, comment on the ticket. The label's own consumer handles the ticket.
- Lane approved at head with red CI: adopt it. `ci-redrive.py` owns it from then on.
- **Backstop for kinds nobody has listed yet:** a tick at the ceiling that finds nothing movable and nothing in the table releases the oldest own PR past the merged cycle-time tail and pages once with its classification. `work_item_age.py` already computes the p85. Use the larger of 10 x p85 and 3 days (measured max: 2.99 days). This keeps the guarantee true when a new hold kind appears.
- A close is reversible (reopen the PR). Branches are never deleted, and the destructive-op hook blocks that anyway. Every release writes one Linear comment and one attempts-ledger row through the existing single writer.

**Why this is a guarantee.** At the ceiling, each tick releases one unmovable PR, so U unmovable PRs are gone in at most U ticks. A movable PR either merges or hits a cap, and every cap is finite, so it then becomes releasable. The count drops below 5 at most (count minus 4) release ticks after the last movable PR resolves. Today that is 9 - 4 = 5 ticks, 75 minutes. The only remaining stops are external outages, and those page.

**Red-first check.**
- New `q-system/.q-system/scripts/test/test-worker-wip-liveness.sh`, on the fixture harness of `test-worker-wip-ceiling.sh` (stubbed gh and Linear, scratch state dir, never the live one).
- Fixture: today's 8 unmovable shapes (cap with REQUEST CHANGES; cap with APPROVE and DIRTY; cap with APPROVE at an old head and the ticket Done; alert ticket; 5 lanes, 3 capped and 2 not).
- Red on main: `kipi work` (dry) prints "Starting nothing" and names no action. A 10-tick simulated loop never drops below 8.
- Green: each tick names one `[dry] would release PR #N (<kind>)`. A 10-tick loop, where the fixture applies each release, reaches `[dry] would work ASK-...` by tick 5.
- Negative self-tests: 5 PRs that are all movable release nothing; a PR approved at head with CI pending and 1 hour old is not released by the backstop; a mutant that deletes the `wip_release` call turns the test red.
- Coverage lint in the same test: every kind that `wip_move_why` or the picker emits has a row in the exit table. A new kind with no row fails.

**Do ASK-3824 and ASK-3833 cover it? No.**
- ASK-3824 covers the 5 cap sites. It ends in one page, with the PR still open, so the ceiling would keep counting it forever.
- ASK-3824 does not cover lanes, alert-ticket PRs, closed-ticket PRs, approved lanes with auto-merge off, lanes with red CI, or the ceiling's own no-movable branch.
- ASK-3833 (do not charge timed-out rounds, meter spend through `model_gate`) is about review accuracy and cost. The release step does not need it. The block relation should stay on ASK-3824 only.
- ASK-3866 already describes this exact defect. It is alert-shaped with no DoR, so the worker can never pick it. The next session converts it: strip `needs-triage` and the alert fingerprint, and add a DoR built from this section.

**How it lands while the worker is locked.**
- Not by the worker. The next supervised Sana session does the Q4 unjam first. Q4's closes alone bring the count to 4, so the worker moves again before the fix lands.
- That session then lands ASK-3866 as one PR on `sana/ask-3866`, a worker-shaped branch, so the worker can rework it and auto-merge gets armed.
- If 5 unmovable PRs build up again before it merges, the session runs `kipi work --issue ASK-3866 --apply`. That per-ticket escape is the one the #613 reviewer named.
- Once it lands, a locked worker releases its own way out, so this bootstrap problem cannot happen again.

## Q4. The unjam for today

Goal: under 5 open own PRs on the next tick, with no work lost (every branch kept). Done by the next supervised Sana session, not the founder.

| PR | Call | Reason |
|---|---|---|
| #543 ASK-2810 | Finish supervised | Approved at its head; only a rebase is missing. Rebase, run one deliberate review past the cap (`KIPI_REVIEW_MAX_ROUNDS=4` for that call, stated on the PR), merge. |
| #559 ASK-2058 | Close, ticket to Backlog | Alert ticket the worker cannot own. REQUEST CHANGES at round 3, with the fix named (scope `is_public()` to origin's refs). Re-file it as a normal owner:sana ticket with a DoR carrying that finding. #435 is an older open PR for the same ticket. |
| #560 ASK-3064 | Leave | The only movable PR; the next tick rebases it. Its adoption repair is reused by the fix. |
| #584 ASK-3574 | Close, ticket stays Done | Verified by hand on 11-01 ("#584 still open as its own item"). The approval is at an old head, and the cap blocks a new review. |
| #606 ASK-3823 | Close, ticket stays Backlog | Round 3 found a real defect (the pre-pass could cancel a live ticket). Add "resume from sana/ask-3823-promoter at 5847c711" to the ticket and put it first in the supervised queue: it is the needs-triage consumer. |
| #609 ASK-3821 | Finish supervised | Approved at its head. Only `validate` is red, on its own diff (function order, CI git identity). Fix it, run one deliberate review, merge. |
| #614 ASK-3827 | Close, ticket stays Backlog | REQUEST CHANGES at round 3 (a review slot recorded with no status post), and conflicting. |
| #618 ASK-3830 | Close, ticket stays Backlog | Round 2 found a design gap (a live receipt judged by command text, so `touch <path>` passes). One round will not finish it, and it is conflicting. |
| #621 ASK-3829 | Finish supervised | One usable round left. The round-2 fix is mechanical (converge.sh and accept-rate.py read only the old file). Fragments end the `.prd-os/receipts.jsonl` conflicts; #560 touches that file and is CONFLICTING. |

After the 5 closes: #543, #560, #609 and #621 stay open. That is 4, under 5, so the next tick starts new work. The 3 supervised finishes should merge before the worker opens 2 more PRs, or the ceiling binds again with 3 unmovable PRs inside it. ASK-3866 landing ends that risk.

## Verification

What I ran, and what came back:
- `kipi work --limit 9` (dry, no `--apply`), 21:05:55Z: "9 open own PRs ... reworks ... PR #560". Passed over: #543 at the round cap, #559 fleet alert, #584 "ticket is Done", and #606, #609, #614, #618, #621 lane branch. Output kept at `/private/tmp/claude-501/-Users-assafkipnis-projects-dev-tools/14b04dc8-cda0-4360-8630-21109bcf42f1/scratchpad/kipi-work-dry-limit9.out`.
- `gh pr view` on all 9: merge state, auto-merge and checks as in the table. Commit statuses: #543 and #609 have `kipi/reviewer-approved` success at head; #584 has "no reviewer verdict at this head".
- `git grep -n "gh pr close"` over tracked code: no hits.
- `gh pr list --state merged` since 10-24: 43 `sana/` merges, 36 lane-shaped, 5 worker-shaped. Cycle time p50 0.05 days, p85 0.17 days, max 2.99 days. `--state closed`, unmerged, since 10-01: 28 `sana/` PRs.
- #560's stall checker (`dispatch-stall-check.py` at `sana/ask-3064`, scratch copy, scratch state, `--replay`): on 4 turns of the ceiling deadlock shape, 0 fires. On 4 turns of a branch-guard skip (the negative self-test), it fires on turn 3 with the repair "PR #606 sana/ask-3823-promoter -> sana/ask-3823". So #560 does not catch this deadlock.
- `linear-worker.sh` has no `issue_runner` call. `scope_hook.py` allows edits with no active issue. `.prd-os` has no spec naming ASK-3824, ASK-3833 or ASK-3826. So the age gate is not a second lock.

Not verified:
- The release design is not built. "5 ticks to unlock" is arithmetic, not a measurement.
- Carrying the round count through adoption needs a reviewer change I have not scoped to a line.
- The stall-checker replay used a hand-made log in the dispatch.log shape, not the live log.

## Contributing factors

- A review major whose claim is "never" or "indefinitely" was allowed to ship as nonblocking.
- Spillover from a PR review is auto-filed as an alert ticket that the worker rejects by design, and the alert queue's consumer has been broken since before 11-06.
- The supervised program's lane shape is not one the worker can adopt, lanes are not armed for auto-merge, and the program has no end-of-run step for lanes it leaves open (ASK-3932 covers lanes going quiet, not lanes left behind).
- Review rounds are counted per PR number, so the honest ways out of a capped PR (rebase, adopt) need either a new review or a cap reset.
- No zero-progress detector exists. #560 looks for per-issue skip lines, and the ceiling's stop writes none.

## Fixes shipped

None in the diagnosis, by instruction. ASK-3866 lands the Q3 fix in the PR that commits this file: `wip_release` in `linear-worker.sh`, the exit table `wip_release.kinds` in `terminal-states.json`, the age backstop, and `test-worker-wip-liveness.sh`.

Correction found while building it: the live loop runs `kipi work` dry, then `converge --issue`, and `--issue` skips the WIP block. So a release that acts only under `--apply` would never fire live, and the `kipi work --issue ASK-3866 --apply` escape in Q3 does not reach the release either. The fix adds a dispatcher apply pass: when the dry pick names a release, `kipi-dispatch.sh` runs `kipi work --release-only --apply`, which releases at most one PR and stops before the issue loop.

## Recurrence

Earlier RCA: `rca-prd-os-issues-end-half-done-2026-11-06.md`. Its root causes #2 to #6 named this class ("no machine consumer") and filed ASK-3826 (ceiling) and ASK-3824 (cap consumer). The ceiling half shipped and the consumer half did not, and the shipped half created a new state with no consumer: the ceiling's no-movable branch. The action that failed: ASK-3826's DoR check tested that the oldest PR is picked, but had no liveness case where every PR is unmovable. The answer is the liveness test in Q3, which has to fail on today's main before the fix lands.

Why each of that RCA's other actions did not stop this one:
- ASK-3823, the needs-triage promoter: its fix is #606, which stopped at the review cap and was one of the 8 parked PRs, so the needs-triage queue holding ASK-3866 had no working drain.
- ASK-3824, every cap ends in code: still Backlog, blocked by ASK-3833, and its design ends in one page with the PR still open, so even landed it leaves every capped PR counted at the ceiling.
- ASK-3825, the worker state round-trip: it shipped, but it moves the ticket back to Backlog on fail, cap or park and leaves the PR open, and the open PR is what the ceiling counts.
- ASK-3827, landing #529, #530 and #532 with review depth and verify repeats read from the ASK-1749 size class: it is about review cost, not PR exits, and its own PR #614 was one of the 8.
- ASK-3829, the prd-os ledgers as fragments: it ends the receipts merge conflicts in the prd-os ledgers, not PR exits, and its PR #621 was a lane counted at the ceiling.
- ASK-3830, closed means shipped (runtime receipts for Live deliverables, tracked deferrals): it has no rule for an open PR with no exit, and its PR #618 was a lane inside the deadlock.

## Action items

- [ ] Unjam per Q4: close #559, #584, #606, #614, #618 with branches kept; finish #543, #609, #621 supervised. Owner: Sana. Type: process. Ticket: none needed, these are PR actions.
- [ ] Convert ASK-3866 into the fix ticket, with a DoR from Q3: `wip_release`, the exit table, the backstop, `test-worker-wip-liveness.sh`. Owner: Sana. Type: code. Ticket: ASK-3866.
- [ ] Add to ASK-3824's DoR: its last step after the page closes the PR (branch kept) and requeues the ticket. Owner: Sana. Type: code. Ticket: ASK-3824.
- [ ] Re-file ASK-2058's guard as a normal owner:sana ticket with a DoR carrying the round-3 finding. Owner: Sana. Type: code. Ticket: ASK-2058.

## Lessons

- A WIP limit is half a pattern. The other half is the drain. Port both or neither.
- A cap that pages and leaves the item open is not a consumer. A consumer changes the item's state.
- A reviewer that predicts "starts nothing indefinitely" has found a blocker, whatever the label says.
- Supervised runs must leave nothing the unattended worker cannot pick up.

## Proposed rule

### RULE-2026-11-07-A: The fleet worker never sits at zero progress with no automated way out
- **Origin:** [USER-DIRECTED] (founder, verbatim: "We cant have things be totally stuck with no recourse")
- **Decision:** Every worker tick at a repo does one of four things: works an issue, reworks a movable PR, releases one unmovable PR through a coded exit, or names an external outage that pages once and has an expiry. A stop, cap or ceiling that holds work without one of these exits is a defect. A release closes a PR or adopts it onto a worker branch. It never deletes a branch and never resets a review cap. A kind of hold with no exit row fails the coverage lint.
- **Reason:** Measured 2026-11-07: 9 open own PRs in kipi-system, 1 movable. After it, 8 unmovable PRs against a ceiling of 5, and the worker starts nothing on every tick. No tracked code closes a PR. #613's review predicted this (sp-55e61d4b, filed as ASK-3866), and it shipped as nonblocking. Source: this RCA.
- **Date:** 2026-11-07
- **Held by:** not yet wired. Will be held by `wip_release` in `q-system/.q-system/scripts/linear-worker.sh`, called from the WIP ceiling block in place of the "Starting nothing" branch, with its exit table in `q-system/.q-system/terminal-states.json` and the liveness check `q-system/.q-system/scripts/test/test-worker-wip-liveness.sh`. Ticket: ASK-3866. Expires: 2026-12-07.
- **Revisit:** Only on a founder order.
