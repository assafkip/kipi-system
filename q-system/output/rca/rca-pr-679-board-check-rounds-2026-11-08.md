# RCA: PR #679 did not converge in its rounds, because each fix wrote a new alert line without reading what consumes it

**Date:** 2026-11-08
**Trigger:** iteration-speed rule 6 on kipi-system PR #679, ASK-4089. A fresh Sana lane (sana-route) took the PR after the dead-end audit lane's session ended.
**Surface-fix commit:** 218d324f
**Structural-fix commit:** none in this PR. ASK-4108 (action item 2).

## What happened

PR #679 makes linear-route.py refuse a route to a project that is not on the Linear board.

- Review round 1 (on 2b824245, `pr-679-20261108-153618.md`) found the refusal had no consumer, plus two minors and a nit.
- Fix round 1 (10d0b705) added a breach line to `linear-triage-health.py` that named the off-board projects.
- Review round 2 (delta 2b824245..10d0b705, `pr-679-20261108-154936.md`) found that the names broke alert dedupe. One condition opened up to 2^k - 1 permanent tickets. It also found a minor: no flag said whether the board check ran.
- Fix round 2 (218d324f) was committed at 00:23Z in `~/.config/kipi/worktrees/ask-4089` and never pushed. The lane's session was cleared at 00:40Z under D35.

So the PR sat at REQUEST CHANGES with its fix on local disk only.

## Surface symptom

Round 2 major, `linear-triage-health.py:937` at 10d0b705:

    out.append(f"{len(refused)} route(s) name a project not on the board ({names})")

`alert-to-linear.py fingerprint()` strips digits, paths, file names and punctuation, then hashes the words that are left. Project names are words, so every name subset gave a different fingerprint.

## Surface root cause

Round 1's fix answered "N refused alone cannot say which row to fix" by putting the names in the line. That line goes into a fingerprint that only works on a closed vocabulary. The sibling breach two lines above says so in its own comment ("NAMED from the router's closed kind vocabulary"), and `notify()`'s docstring says the dedupe is by shape.

## Structural root cause

### Root cause #1
type: process

Round 1's recon read the producer (linear-route.py's refusal) and the place the new line was written (`breaches()`). It did not read the consumer of that line (`notify()` into `alert-to-linear.py fingerprint()`). The contract that broke was written down in two places within 25 lines of the edit. Each round fixed the finding it was given. No round asked what reads the new output and what that reader assumes about it.

### Root cause #2
type: missing-test

The round 1 test asserted that the names appeared in the line. That test pinned the defect in place. Nothing in the suite runs a `breaches()` line through the real `fingerprint()` while the population under it changes. 218d324f adds that check for this one line only (`test_the_off_board_breach_is_one_ticket_whatever_the_names`). The next breach line anyone adds to `breaches()` can bring the same defect back, and no test would catch it.

### Root cause #3
type: process

The handoff at 00:40Z (`~/.config/kipi/handoffs/2026-11-09-orchestrator-handoff.md`) says "Every local branch is pushed and matches origin". It lists three branches. sana/ask-4089-board-check was not one of them. 218d324f was 17 minutes old and unpushed. The handoff checked the branches the orchestrator knew about. It did not check the worktrees on disk. So a finished fix round looked like a PR waiting for rework, and the hold comment on #679 (00:37Z) put off a fix that already existed until after the usage reset.

## Verification

- Ran `git -C ~/.config/kipi/worktrees/ask-4089 log --oneline -3` and `git log -3 origin/sana/ask-4089-board-check` at 01:23Z. Local was at 218d324f (`git log -1 --format=%ci`: 2026-11-08 16:23:25 -0800, so 00:23Z). Origin was at 10d0b705. No lane marker for ASK-4089 existed in `~/.config/kipi/lanes/`.
- Ran `python3 -m pytest -q tests/test_linear_route.py tests/test_linear_triage_health.py` at 218d324f and got 129 passed.
- Mutation, run on a scratch copy and never in the worktree:
  - Put back the 10d0b705 names line. `test_the_off_board_breach_is_one_ticket_whatever_the_names` failed with `assert 3 == 1`, which is three fingerprints from one condition, the reviewer's reproducer exactly.
  - Removed `board_check_ran` from `route_pending()`. `test_the_board_check_flag_survives_the_subprocess` failed.
  - Result: 2 failed, which means both mutants were killed.
- Review round count: `pr-review-agent.sh` counts the usable review files `assafkip_kipi-system__pr-679-*.md` in `~/.config/kipi/pr-reviews/`. There are 2. The hold comment called the second one "Round 3". The next review is the counter's round 3.

## Contributing factors

- The network outage on this Mac (about 00:00 to 00:30Z) overlapped the window when 218d324f would have been pushed.
- Delta review is right on cost. But a delta that adds one alert line does not show the reader of that line, so the reviewer found the defect by reading `notify()` on purpose. Fix round 1 had no equivalent step.
- Round numbers did not agree. The hold comment counted 3 and the counter counts 2, so the cap could not be judged from the comment.

## Fixes shipped

- Surface fix: the breach line gives the count and names the command that lists the projects, with no project names in it. `measure()` reports `board_check_ran`, and a report-only run prints NOT MEASURED when the project list could not be read. Commit 218d324f.
- Structural fix: not in this PR. The class is "a breach line whose words change with the population". The test that prevents it is action item 2.

## Action items

- [ ] Push 218d324f and run the review on the delta 10d0b705..218d324f. Done when kipi/reviewer-approved is success at the head. — owner: sana-route lane, tonight — type: process
- [ ] Add a test that drives every `breaches()` line in `linear-triage-health.py` through `alert-to-linear.py fingerprint()` with two different populations and requires one fingerprint per condition. Done when it is merged and a mutant that adds a name to any breach line fails it. — owner: Sana, ASK-4108 (owner:sana), picked by the fleet worker once dispatch resumes — type: test
- [ ] Make a handoff's "every branch is pushed" claim come from the disk: `git -C <each tree in git worktree list> log @{u}..HEAD`, not a static list of branches. — owner: the orchestrator's handoff step, reported to the orchestrator by this lane — type: process

## Lessons

- Before you add a line to an alert, read the code that fingerprints it. Dedupe by shape needs a closed vocabulary.
- A test that asserts a value appears in an alert line can pin a defect in place. Test the property the consumer needs.
- "Pushed" is a fact about the disk. Check every worktree, not the branches you remember.
