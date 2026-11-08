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
- Green on the fix: 127 checks, PASS at e02d7f70, and 130 after the round-4 minors. #9 and #11 get ASK-9001 and ASK-9002, each naming its own PR. pr-owner records the ticket the sink named. #12 reads `young` and #14 reads `wait`. #10 reads `ladder` through the real ladder_owns() of PR #662 (b3edcfda, read from origin/sana/ask-3824-ladder). 49 hours later, neither fork is alerted again: 2 tickets, 0 comments.
- Exit 0 with no ticket: the real capture hatch (KIPI_ALERT_CAPTURE) returns 0 and names no ticket. act() returns not-ok and records nothing.
- The review runner: a stub `kipi` that leaves `( sleep 20 ) &` holding its stdout, run as a real subprocess through act(). On the round-3 code the call took 20.0s. On the fix it returns at once, and the stub's output is in pr-owner's review log.
- Round 4 (delta 959e037b..e02d7f70): APPROVE WITH NITS, kipi/reviewer-approved=success. Its nonblocking major went to ASK-4056. Measured 2026-11-08 ~22:05Z: the shared and pinned registries name the same dispatch rows (ktlyst, brag), so no instance is missed today. Both minors are fixed red-first. A failed requeue now returns not-ok and names itself; it was (True, "rework asked; note posted"). Every REFUSED exits 3; an unreadable state file exited 1.
- Mutants, each run once on a sibling copy and then removed: 12 of 12 KILLED after round 4. The first 10 were KILLED at e02d7f70. They were: a constant ref, a CAP_TICKET-style a-j PR-number ref, exit 0 read as a record, provenance before the gates, no ladder branch in decide, a fallback that yields nothing, a broken ladder read as not owned, the ladder not asked in main, fork commits not read, the review read through a pipe, a failed requeue read as ok, and a refusal exiting 1.

## Contributing factors

- The alert sink's dedup is documented in its own file (alert-to-linear.py `_VOLATILE`) and in pr-review-agent.sh, which already met this exact bug at PR #501 and fixed it by spelling the PR number in letters. Round 2 did not read either before adding the call.
- Each round fixed the flagged line and did not re-derive the table around it. Round 2 moved one constant (UNSTABLE) back across the line round 1 had moved it over.
- The previous agent's session lost Bash and Edit when the rule_gate.py hook directory went missing, so round 3's fixes could not be made before the cap.

## Fixes shipped

- Surface fix: the fork alert ends with `Dedup key ref<16 letters>`. That is a sha256 of `owner/repo#n` spelled in the letters g to v, so no rule in alert-to-linear.py's `_VOLATILE` strips it (no slash, no digit, no hex run). It differs per PR and stays the same across runs for one PR. pr-owner records the alert only when the sink's first stdout line matches alert-to-linear.py's own `_FILED_LINE` (imported, not copied), and it stores the ticket identifier. Any other exit 0 is a failed act, so the next hourly run asks again.
- Surface fix: decide() runs the 48h age and 12h quiet gates before the provenance branch. main() reads an aged fork's commits, and nothing else of it, so the quiet gate has a last push.
- Structural fix: test-pr-owner.py drives the real sink and the real ladder. The round-3 fake that returned success for every alert is gone, and fake_run refuses any slack-notify.sh except the temp copy.
- Same change, found by the Sonnet vs Opus agent: the review runs through run_logged(), with its output in a file under ~/.local/state/kipi/pr-owner/reviews/. A pipe would wait on pr-review-agent.sh's watchdog `sleep` (line 334) for up to 40 minutes after the review ended.
- Same change, from the handoff: decide() yields every PR cap-ladder.py's ladder_owns() claims (`ladder`, no write). With no cap-ladder.py in the checkout (PR #662 not merged), pr-owner yields a superset: any review-cap marker for the PR, or any worker-attempts record for a sana/ask-N ticket. So the two jobs never both write one PR.

## Recurrence

<!-- rca-recurrence-skip -->
No earlier RCA in this directory covers pr-owner.py or the alert sink's fingerprint as a caller contract. The nearest is the PR #501 fix in pr-review-agent.sh (CAP_TICKET), which is a code comment, not an RCA.

## Action items

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
