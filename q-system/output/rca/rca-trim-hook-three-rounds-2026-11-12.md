# RCA: Bash output trim hook lost records three review rounds running while its footer said nothing was dropped

**Date:** 2026-11-12
**Trigger:** PR #764 (ASK-4649) hit the review round cap (3) with a major finding open in rounds 2 and 3
**Surface-fix commit:** 5a2d02da (refuse a trim that selected nothing away)
**Structural-fix commit:** see PR head (one commit after 5a2d02da)

## What happened

The tool-output-trim hook shortens large Bash output and appends a footer, "showing k of t lines". Round 1 found coloured git diffs and spill-file retention. Round 2 found carriage-return (CR) records collapsed to their last segment. Round 3 found the same collapse again with one stray LF in the input. Each round got a patch for its instance and the next round found the next instance.

## Surface symptom

Round 3 footer over 801 CSV records: `[trim: showing 1 of 1 lines; full output (16608 chars)]`. Measured on head 5a2d02da with an LF log that contains one CR-separated chunk in the middle (300 LF rows, 400 CR rows, 300 LF rows):

```
lf_log_with_cr_chunk -> footer total 601, real records 1000
```

400 rows are gone and the footer does not say so.

## Surface root cause

`clean_lines` in `q-system/.q-system/scripts/tool-output-trim.py` splits on LF and then, per line, keeps only the last CR-separated segment. Rounds 2 and 3 added a branch that turns CR into LF when the text has no LF at all, and then a refusal when nothing was selected away. Both fire only when the whole output collapses. A CR chunk inside an LF log collapses locally, `kept < lines` is true, and neither guard sees it.

## Structural root cause

### Root cause #1

The footer's `t` is computed after the lossy step (`len(lines)` is the count after CR collapse), so the number that is supposed to prove nothing was lost is derived from the thing that loses it. No test compared `t` to the input's own record count.

type: missing-test

### Root cause #2

Redraw (`10%\r20%\r30%`) and records (`a,1\rb,2`) are indistinguishable in bytes, and the code decided between them with a heuristic on the whole output. Every patch moved the heuristic's boundary (zero LF, then any LF). A decision that cannot be made from the input should be removed, not tuned.

type: implicit-contract

### Root cause #3

Each fix carried a mutant whose killer test was written from inside that fix's own model (`cr_records` flips the new branch, the pure-CR test kills it). The suite could not see the neighbouring input. The oracle came from the fix, not from the invariant.

type: missing-test

### Root cause #4 (answered, not a cause)

Round 3 asked whether Claude Code hands a PostToolUse hook raw CRs at all. Live probe, `claude -p` running `printf 'rowA\rrowB\rrowC\nlineD\n'` with a hook that logs stdin bytes: `tool_response.stdout` arrived as `'rowA\rrowB\rrowC\nlineD'`. CRs reach the hook unchanged. The class is reachable; it was not a theoretical hole.

type: environmental-trigger

## Verification

Ran the scratch invariant script against head 5a2d02da and got the failure (footer total, real records, kept):

```
lf_log_with_cr_chunk -> (601, 1000, 71)   tot==n? False
progress_redraw      -> (401, 501, 71)    tot==n? False
```

Ran the live probe and observed raw CRs in `tool_response.stdout`. After the structural fix the same script and the new property test are re-run; their output is in Fixes shipped.

## Contributing factors

- Four majors in three rounds on code that barely moved. The review text named it in round 3: the fix shape was wrong, not the reviewers' luck.
- The footer is prose the model trusts. A false "showing 1 of 1" is worse than no footer.
- Review cap of 3 rounds forces a fresh agent to start from an RCA, which is what this file is.

## Fixes shipped

- Surface fix: 5a2d02da refuse any trim where nothing was selected away. Closes the all-collapsed case only.
- Structural fix: `clean_lines` splits on every CR, LF or CRLF (no redraw rule). Fold markers carry a weight so "N lines omitted" counts input records, and the blank-run special case that dropped lines with no marker is gone. Property test `test_footer_total_is_the_input_record_count_for_every_input` (120 generated mixed-separator outputs, oracle is the generator's row count) asserts footer total == records and kept + omitted + folded == records. Ran it: 41 passed in 18s (the file, 18 mutants included). Negative self-test: mutants `cr_collapse` (old collapse) and `omit_weights` (raw line count) both go red on that test. The same scratch script as before now gives `(1000, 1000, 71)` for the LF log with a CR chunk and `(501, 501, 71)` for the redraw case.
- Also found while writing the property test: a second instance of the class, the omitted count ignoring folds hidden inside an omitted range. Fixed by the same weights, not a separate patch.
- Uncommitted carve-out for `cat`/`head`/`sed -n` reads was dropped: it adds a command-regex heuristic (bypassable the way `GIT_DIFF_CMD_RE` is), does nothing for the invariant, and its test run never finished.

## Recurrence

- 2026-11-10-ask-4311-pr717-three-rounds.md: action "land the invariant as the first test" was not taken here either. This hook's first test pinned the output shape of three fixtures, not the accounting identity, and the same capped-round pattern followed.

## Action items

- [ ] Replace the CR heuristic with one splitter so the footer total is the raw record count — owner: sana — type: code
- [ ] Property test: footer total equals raw record count, and kept plus omitted plus folded equals total, over generated LF, CR, CRLF mixes — owner: sana — type: test
- [ ] Mutant that restores the CR collapse and must fail the property test — owner: sana — type: test
- [ ] Round-3 minors 3 and 4 (scope note wording, recovery path re-trimmed) go to a follow-up Linear issue for Sana — owner: sana — type: process

## Lessons

- When a lossy filter prints a count, derive the count from the input, never from the filter's own output, and test the identity over generated input before testing any single shape.
- If a decision cannot be made from the bytes, delete the decision. Tuning its boundary is a patch per round.
- A mutant's killer test must come from the invariant, not from the fix it mutates.
