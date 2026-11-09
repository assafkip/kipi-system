# RCA: three review rounds on PR #659 each found pr-owner.py trusting its own model of an outside contract

**Date:** 2026-11-08
**Trigger:** the 3-round review cap (iteration-speed rule 6) on kipi-system PR #659, ASK-3962. Round 3 was REQUEST CHANGES at head 959e037b.
**Surface-fix commit:** filled in below, after the round-3 fixes land
**Structural-fix commit:** filled in below

## What happened

PR #659 adds pr-owner.py, an hourly job that gives every open fleet PR an owner whatever its branch prefix. Three review rounds each returned REQUEST CHANGES. Each round's major finding sat at a point where pr-owner.py reads or writes through code it does not own: GitHub's merge state in rounds 1 and 2, and alert-to-linear.py's dedup in round 3. The handoff agent (a fresh Sana) writes this RCA, then fixes round 3 and continues.

## Surface symptom

Review records under ~/.config/kipi/pr-reviews/, assafkip_kipi-system__pr-659-*.md, and the three reviewer comments on ASK-3962:

- r1 major: fork PRs acted on with no isCrossRepository read, so an author-chosen branch name bound a stranger's PR to a real ticket. r1 major: MERGE_READY accepted UNSTABLE and the merge branch ran before the CI read, so an approved PR could merge with CI red.
- r2 major: the r1 fix dropped UNSTABLE, so an approved PR whose only non-green status was the advisory kipi/codex-approved went to rework, then close. r2 minor: a fork PR's only output was a line in pr-owner.log, which no script reads.
- r3 major: the r2 fix filed the fork alert through slack-notify.sh. alert-to-linear.py's fingerprint strips `\S*/\S*` and `\d+`, so the slug, URL and PR number are gone and every fork PR hashes the same. The second one is a "repeat (counted)" on the first one's ticket, exit 0, and pr-owner records it filed forever. r3 minor: the fork branch returned before the 48h age and 12h quiet gates.

## Surface root cause

`act()` for `outside` treated slack-notify.sh exit 0 as "a ticket names this PR". Exit 0 also means a counted repeat on another PR's ticket, a noise suppression, a sustained-rule deferral and a capture. And the message carried the PR's identity only in tokens the sink's normalizer deletes.

## Structural root cause

### Root cause #1
type: implicit-contract

Each round added a dependency on a contract pr-owner.py does not own (GitHub's mergeStateStatus values, slack-notify's exit codes, alert-to-linear's fingerprint), and wrote the code against a belief about that contract instead of reading it. The belief was wrong each time in a way only the other side's code shows: UNSTABLE covers advisory statuses that ci_state already ignores, and exit 0 covers four outcomes that file nothing for this PR.

### Root cause #2
type: missing-test

The tests encoded the same belief as the code, so they could not fail. Round 3's test asserted that the alert MESSAGE names the PR (`"PR #9" in a[2]`), which is true and irrelevant: the dedup key is computed after the normalizer deletes that substring. The fake for slack-notify.sh returned `0, "", ""` for every call, so "a second fork PR" was never a case the suite could see. Round 2's fix of the merge-state line was tested against a hand table, not against ci_state on a real rollup shape.

## Verification

All on fixtures. test-pr-owner.py asserts its state path and worker state dir are under a temp dir before anything runs.

- The harness: a temp copy of the real slack-notify.sh runs as a subprocess. Its alert-to-linear.py is a wrapper that runs the REAL alert-to-linear.py main() (fingerprint, lock, dedup, create), with the Linear transport replaced by a JSON file and urlopen blocked.
- Red at 959e037b: the final test-pr-owner.py run against the 959e037b pr-owner.py fails 26 checks. The sink shows the major exactly: fork #9 files ASK-9001, fork #11 lands as a counted repeat on it, and pr-owner records both as filed. Fork #12 (open 1h) and fork #14 (pushed 1h ago) are alerted. Ladder-owned #10 gets a rework comment and a Linear note. Four fork PRs, two of them #2 in different repos, share one fingerprint.
- Green on the fix: 127 checks, PASS at e02d7f70, 130 after the round-4 minors, 137 after round 5, 140 after round 6. #9 and #11 get ASK-9001 and ASK-9002, each naming its own PR. pr-owner records the ticket the sink named. #12 reads `young` and #14 reads `wait`. #10 reads `ladder` through the real ladder_owns() of PR #662 (b3edcfda, read from origin/sana/ask-3824-ladder). 49 hours later, neither fork is alerted again: 2 tickets, 0 comments.
- Exit 0 with no ticket: the real capture hatch (KIPI_ALERT_CAPTURE) returns 0 and names no ticket. act() returns not-ok and records nothing.
- The review runner: a stub `kipi` that leaves `( sleep 20 ) &` holding its stdout, run as a real subprocess through act(). On the round-3 code the call took 20.0s. On the fix it returns at once, and the stub's output is in pr-owner's review log.
- Round 4 (delta 959e037b..e02d7f70): APPROVE WITH NITS, kipi/reviewer-approved=success. Its nonblocking major went to ASK-4056. Measured 2026-11-08 ~22:05Z: the shared and pinned registries name the same dispatch rows (ktlyst, brag), so no instance is missed today. Both minors are fixed red-first. A failed requeue now returns not-ok and names itself; it was (True, "rework asked; note posted"). Every REFUSED exits 3; an unreadable state file exited 1.
- Round 5 (delta e02d7f70..d2c8b54e): APPROVE WITH NITS. Its nonblocking major was the merge-state table again: an approved, green, MERGEABLE PR that GitHub calls BLOCKED or UNKNOWN went to rework, then close. pr-verdict-lib.sh rework_gate, the repo's one reader of that field, calls both terminal. Fixed by asking rework_gate, not copying it, and driving the real lib in the test. Red: close-requeue on BLOCKED, UNKNOWN and an omitted field. Green: wait, and BEHIND still a rebase round. Both minors and the nit are fixed red-first: a hold now exits 2, and -h exits 0.
- Round 6 (delta d2c8b54e..152993df): REQUEST CHANGES. The major: state["closed"] was written and never read, so a reopened PR was closed again on the next hourly run, which broke the "Reopen this PR to undo" the close comment promises. The bug had been there since ce463a10, and no round tested it. Fixed red-first: a PR open at the head pr-owner closed it at reads `reopened` until a new push. Red: a second `gh pr close` on #1. Its two minors are handled on #659 and in a follow-up ticket, not in this push.
- Mutants, each run once on a sibling copy and then removed: 18 of 18 KILLED after round 6, and 16 of 16 after round 5. 12 were KILLED after round 4 and the first 10 at e02d7f70. They were: a constant ref, a CAP_TICKET-style a-j PR-number ref, exit 0 read as a record, provenance before the gates, no ladder branch in decide, a fallback that yields nothing, a broken ladder read as not owned, the ladder not asked in main, fork commits not read, the review read through a pipe, a failed requeue read as ok, a refusal exiting 1, rework_gate's terminal answer ignored, its unknown answer read as red, a hold counted healthy, and -h exiting 64.

## Contributing factors

- The alert sink's dedup is documented in its own file (alert-to-linear.py `_VOLATILE`) and in pr-review-agent.sh, which already met this exact bug at PR #501 and fixed it by spelling the PR number in letters. Round 2 did not read either before adding the call.
- Each round fixed the flagged line and did not re-derive the table around it. Round 2 moved one constant (UNSTABLE) back across the line round 1 had moved it over. Round 5 found two more states of that same table (BLOCKED, UNKNOWN), which is the evidence for asking pr-verdict-lib.sh instead of keeping a copy.
- Rounds 4 to 6 (the handoff agent) each found a defect on surface no earlier round had exercised. Rounds 1 to 3 had the same pattern. Neither the author nor the reviewer made a list of what the file PROMISES (docstring and comment claims such as "Reopening the PR undoes it" and "a few PRs one more day") and tested each one. The rounds tested the write edges each finding pointed at. Next round: list every promise in pr-owner.py's docstrings and the comments it posts, give each one a check, then review.
- The previous agent's session lost Bash and Edit when the rule_gate.py hook directory went missing, so round 3's fixes could not be made before the cap.

## Fixes shipped

- Surface fix: the fork alert ends with `Dedup key ref<16 letters>`. That is a sha256 of `owner/repo#n` spelled in the letters g to v, so no rule in alert-to-linear.py's `_VOLATILE` strips it (no slash, no digit, no hex run). It differs per PR and stays the same across runs for one PR. pr-owner records the alert only when the sink's first stdout line matches alert-to-linear.py's own `_FILED_LINE` (imported, not copied), and it stores the ticket identifier. Any other exit 0 is a failed act, so the next hourly run asks again.
- Surface fix: decide() runs the 48h age and 12h quiet gates before the provenance branch. main() reads an aged fork's commits, and nothing else of it, so the quiet gate has a last push.
- Structural fix: test-pr-owner.py drives the real sink and the real ladder. The round-3 fake that returned success for every alert is gone, and fake_run refuses any slack-notify.sh except the temp copy.
- Same change, found by the Sonnet vs Opus agent: the review runs through run_logged(), with its output in a file under ~/.local/state/kipi/pr-owner/reviews/. A pipe would wait on pr-review-agent.sh's watchdog `sleep` (line 334) for up to 40 minutes after the review ended.
- Same change, from the handoff: decide() yields every PR cap-ladder.py's ladder_owns() claims (`ladder`, no write). With no cap-ladder.py in the checkout (PR #662 not merged), pr-owner yields a superset: any review-cap marker for the PR, or any worker-attempts record for a sana/ask-N ticket. So the two jobs never both write one PR.

## Rounds 4 to 6 (the handoff agent's three)

Written by the round-7 agent (a fresh Sana), per iteration-speed rule 6.

- **What happened.** Round 4 found a failed requeue reported as ok and refusals exiting 1. Round 5 found an approved PR that GitHub calls BLOCKED sent to rework and close. Round 6 found that a reopened PR was closed again the next hour. Each fix was correct and red-first. Each next round still found new surface.
- **Surface cause.** Every finding was a sentence the file itself says, which the code did not do. Round 6 is the plain case: the close comment says "Reopen this PR to undo", and `state["closed"]` was written and never read, from the first commit (ce463a10) on.
- **Structural cause (type: missing-test).** Nobody listed what pr-owner.py promises and tested each one. The tests followed the code paths each finding named. A promise no finding named had no test, so the suite could not fail on it. Rounds 1 to 3 had the same shape against outside contracts; rounds 4 to 6 had it against the file's own words.
- **Fix.** test-pr-owner-contract.py. It lists every promise in the docstrings, comments, posted PR comments, ticket notes and log lines. Each promise gets one assertion that runs the real decide(), act() and main() on a faked fleet. A coverage check fails when a promise-shaped line in pr-owner.py (never, only, at most, once, undo, refuse, exit N, nothing else) has no promise row or written exemption. So a new claim cannot land untested.
- **Verification.**
  - Red on f4748e76 (pr-owner.py unchanged): 5 checks failed. Two are real defects. P06: an archive hook that exits 1 with no output read as an allow, so the repo was listed and its PR closed, exit 0, while the comment said "a guard that cannot answer is a deny". P14: the rework comment told a Todo ticket it "goes back to Backlog", but only a started ticket is requeued. A third failure was P06 cascading. The last two were anchors of mine that split across a wrapped line.
  - Fixed red-first. archived() raises on any non-answer, and main() counts that repo unread, so the run exits 2. The rework comment says "goes back to Backlog" only for a started ticket. The docstring now names the fork alert as the second Linear write path.
  - Green: test-pr-owner-contract.py, 46 promises and 97 assertions, PASS. test-pr-owner.py still has 140 checks, PASS.
  - Mutants: 16, each a mutated pr-owner.py in a temp dir run against the contract test. 15 were killed on the first pass. The no-age-gate mutant lived: every young fixture was also under the 12h quiet gate. A 30h-old PR now covers that, and 16 of 16 are killed.
  - The coverage rule caught 4 promise-shaped lines in this fix's own comments before they had rows.

## Recurrence

<!-- rca-recurrence-skip -->
No earlier RCA in this directory covers pr-owner.py or the alert sink's fingerprint as a caller contract. The nearest is the PR #501 fix in pr-review-agent.sh (CAP_TICKET), which is a code comment, not an RCA.

## Action items

- [x] Every promise pr-owner.py makes has one assertion that drives the real code, and a new promise-shaped line with no row fails CI (test-pr-owner-contract.py); owner: Sana (ASK-3962 round-7 agent); type: test
- [x] The fork alert carries the PR's identity in a token alert-to-linear.py's normalizer keeps, and pr-owner records it filed only when the sink's stdout names a ticket; owner: Sana (ASK-3962 handoff agent); type: code
- [x] The fork branch sits behind the 48h age and 12h quiet gates; owner: Sana (ASK-3962 handoff agent); type: code
- [x] test-pr-owner.py drives the real slack-notify.sh and alert-to-linear.py main() (fake transport only) and the real cap-ladder.py ladder_owns(); no hand model of either sink; owner: Sana (ASK-3962 handoff agent); type: test
- [x] pr-owner.py yields every PR cap-ladder.py owns, through ladder_owns() from PR #662; owner: Sana (ASK-3962 handoff agent); type: code
- [x] Round 4 on PR #659 reads only the delta since 959e037b; owner: pr-review-agent.sh, run by the ASK-3962 handoff agent; type: process. Done: APPROVE WITH NITS, minors fixed, round 5 reads the delta since e02d7f70.

## Lessons

- When a change calls code it does not own, the test drives that code, not a fake of its answer. A fake that returns success for every call can only confirm the author's belief.
- Exit 0 from a deduping sink means "the sink is satisfied", not "this item has a record". Read the record the sink names.
- Before adding a call to a shared sink, grep for the callers that already met its contract. pr-review-agent.sh had the letters fix for this dedup since PR #501.
- When a review flips a constant, re-derive the whole decision table from the other side's code before moving it back.
