# RCA: kipi-system PR #839 approved, then stranded by a merge from main (3-round review cap)

**Date:** 2026-11-18
**Trigger:** PR #839 (ASK-4969 D1, ships `part_runs.py`) was approved at 060b3038 with checks green. #840 then bumped `plugins/kipi-core/.claude-plugin/plugin.json` on main, #839 went CONFLICTING, the merge head 55e215b0 carried no `kipi/reviewer-approved`, and `pr-review-agent.sh` refused a round 4. ASK-5411 (consulting carry) waits on #839.
**Surface-fix commit:** 55e215b0 (merge of origin/main, kipi-core 1.13.72 over main's 1.13.71)
**Structural-fix commit:** PR #845, branch `sana/carry-merge-only-ask-4969` (see Fixes shipped)

## What happened

- Reviews on #839, from `~/.config/kipi/pr-reviews/`:
  - `pr-839-20261118-122259.md`: REQUEST CHANGES (usable)
  - `pr-839-20261118-125549.md`: 0 bytes, a run killed mid-flight (unusable)
  - `pr-839-20261118-130712.md`: APPROVE WITH NITS (usable)
  - `pr-839-20261118-132618.md`: APPROVE WITH NITS (usable), approved head 060b3038
- Main moved (#837, #838, #840). #840 bumped kipi-core 1.13.71. #839's own bump was 1.13.70, so the merge resolved to 1.13.72.
- The merge head 55e215b0 has no verdict. `kipi/reviewer-approved` is required per sha. The cap is spent. Nothing moved the approval.

## Surface symptom

PR #839 BLOCKED on `kipi/reviewer-approved` PENDING at 55e215b0, and the reviewer refusing another round.

## Surface root cause

The approval is per sha. A merge from main creates a new sha, and the only carry path (`receipt-carry-approval.sh`, ASK-1888) accepted receipt commits and nothing else.

## Structural root cause

### Root cause #1: no carry path for a head moved only by a merge from main
type: implicit-contract

`delta_kind` in `q-system/.q-system/scripts/receipt-carry-approval.sh` returned `other` for any head whose diff against the reviewed sha was not a receipt. A merge from main is the commonest non-receipt move of an approved head, and the cap made it unrecoverable: a new head needs a review, a review needs a round, the rounds were spent. "Nothing picks this up" was the defect. Measured on the real shas: the PR's own diff (patch-id `--stable`, plugin.json excluded) is `e923643976074fcc2de648f7a234488e85b5d0d6` before and after; the only PR-owned file that moved was plugin.json, by its `"version"` line.

### Root cause #2: a version bump that main also makes is a conflict by construction
type: process

Every kipi-core change must bump `plugin.json` (validate is red without it), and every other kipi-core PR on main bumps the same line. So an approved kipi-core PR conflicts the moment any other one lands. The conflict then costs a new head after the last review round. The bump was needed, so it is not a mistake; the cost is that nothing treats a version-only move as non-semantic.

### Retracted premise: an aborted run did not count against the cap
type: process

**Known-answer case:** the same predicate returns USABLE on the three files that hold a findings block (they were counted) and unusable on the 0-byte one, so it can say "not usable" and it did.

The hand-off said an aborted round counted. Measured: it did not. `review_is_usable` (`pr-verdict-lib.sh:272`) needs a complete findings block, no could-not-read, no declined-to-start. The killed run left `pr-839-20261118-125549.md` at 0 bytes, which fails `has_complete_findings_block`, so the cap loop (`pr-review-agent.sh:462`, `PRIOR_ROUNDS`) did not count it. Running `review_is_usable` over the four files gave USABLE, unusable, USABLE, USABLE. The cap was spent by three real rounds: one REQUEST CHANGES, then two APPROVE WITH NITS (the third fixing round 2's nits). What the killed run did cost: a round number (the next file is labelled round 4) and about 20 minutes. A killed run that had already written a findings block would count, and the script has no way to tell it from a finished one.

## Verification

- Proof the delta is merge-only, run in a worktree cut from origin/main:
  - `git range-diff ff31e305..060b3038 9e3aca42..55e215b0`: all 6 PR commits `=`.
  - Name-status of the PR's own files is identical before and after (8 paths).
  - Blob equality of the 8 PR paths between 060b3038 and 55e215b0: 7 identical, plugin.json differs by `1.13.70` to `1.13.72`.
  - `git diff 060b3038 55e215b0` touches 9 files: plugin.json plus 8 of main's files, none of them in the PR.
- Red test first: `test/test-receipt-carry-approval.sh` with the new section read `other` for the merge head (2 FAIL of 90). After the fix: `passed 93, failed 0`, including 3 new mutants (diff equality removed, on-main check removed, version-only check removed), each killed.
- Real shas: `receipt-carry-approval.sh --delta-kind . 060b3038 55e215b0` prints `merge-only`.

## Contributing factors

- The cap is 3, set before carry existed for anything but receipts.
- Round 3 ran after an APPROVE WITH NITS to fix nits, which spent the last round on code that was already approvable. `feedback_round_cap_vs_required_reviewer_status` says reject the last round's minors; the nit fix was made anyway.
- Disk was under the 5 GB worktree floor for part of the session; this held the proof for about 15 minutes.

## Fixes shipped

- `receipt-carry-approval.sh`: `delta_kind` gains `merge-only` (function `merge_only`). Accepted only when all hold:
  - head is a two-parent merge, one parent the reviewed sha;
  - the other parent is an ancestor of the base ref (`RECEIPT_CARRY_BASE_REF`, default origin/main);
  - `git patch-id --stable` of the PR's net diff is equal before and after, on the final tree;
  - any `.claude-plugin/plugin.json` that moved changed `"version"` lines only.
- The carry's other two guards are unchanged (live approval at the reviewed sha, no real verdict on the head). converge's `receipt_only_ahead` matches `receipt-only` exactly, so a merge-only head is never pushed as a receipt.

## Action items

- [x] Sana: add `merge-only` with a red test and three mutants (PR #845) — owner: sana — type: code
- [ ] Sana: run the carry on #839 once #845 merges, record the merge-only evidence on the PR — owner: sana — type: process
- [ ] Sana: a launchd or converge consumer that runs the carry on a PR whose head is a merge-only descendant, so the next one needs no hand — owner: sana — type: code (filed as a Linear issue for Sana if not done in this run)

## Lessons

- A claim that a counter counted something is a hypothesis; run the predicate on the files (`review_is_usable` over four files took one command).
- A per-sha required status needs a rule for every move of the sha that changes none of the PR's own code. Receipts were the first; a merge from main was the second.
