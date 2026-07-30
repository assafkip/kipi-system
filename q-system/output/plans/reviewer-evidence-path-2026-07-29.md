# Reviewer evidence path: the review never reaches a human, and the receipt is unreadable

Date: 2026-07-29 (session clock 2026-07-30 UTC)
Owner: sana. Issue: ASK-221 follow-on.

## What / why

Two defects on merged `main` (`f277389`), both in the same class: the codex
reviewer really runs, and the evidence of it lands somewhere nobody reads.

1. **The review never reaches the PR.** `--post` pipes the RAW codex stdout to
   `gh pr comment --body-file`. Measured: `pr-34-20260729-204820.md` = 435,280 B,
   `pr-34-20260729-210606.md` = 519,377 B. GitHub's comment limit is 65,536 B.
   Every post fails, `pr-review-agent.sh:627` prints `WARN: could not comment on
   PR` and continues, and `post_reviewer_status` then has no `target_url`. A
   human sees a bare green/red status with nothing behind it.
   Verified: PR #34 has 3 issue comments, all authored by `assafkip`, zero codex.

2. **The receipt is grepped from a file nothing writes.**
   `verify-codex-review-live.sh:165-171` greps `~/.config/kipi/dispatch.log` for
   `engine: codex`. That string is produced by `pr-review-agent.sh:255`
   (`round: $ROUND (engine: $ENGINE)`) on **stdout**, which
   `linear-worker.sh:1133` redirects into `$STATE_DIR/linear-worker.log`.
   Worse than a wrong-file bug: `grep -rn 'dispatch.log'` over
   `q-system/.q-system/scripts/*.sh` shows the verifier is the ONLY reference —
   no script in the tree writes that file at all. So check 8 prints
   `NO RECEIPT YET` forever, including after a real dispatcher-driven review.

## Why the obvious fixes are wrong

- **Trimming harness noise does not fit.** The 14-line header is not the bulk.
  `pr-34-20260729-210606.md` is 10,130 lines; the reviewer's actual message is
  the last ~250. Lines 15-9880 are the codex agent's own transcript, which
  includes the diff it read — that is why the file contains 11 `FINDINGS:`
  markers instead of one.
- **Splitting across comments is wrong.** It would put ~8 comments of agent
  transcript on the PR. The transcript is a debugging artifact, not a review.
  GitHub is not an artifact store.

## Approach (the pick)

Options considered: (a) split across N comments, (b) attach as a gist/artifact,
(c) post a bounded rendered review and name the on-disk artifact. **Pick: (c).**

### Fix A — one renderer, bounded, verdict and findings structurally guaranteed

Add `review_comment_body <review-file>` to `pr-verdict-lib.sh`, beside the other
ONE-reader helpers. It emits, in order:

- the verdict, from the verdict the caller already derived (never re-grepped)
- the findings block, via the existing `findings_block` ONE reader
- the tail of the reviewer output, line-aligned, as the human-readable narrative
- a footer naming the full artifact path and its byte size

The verdict and findings come from the ONE reader, NOT from the truncated tail,
so truncation can never drop the two things a human needs. Hard cap under
65,536 with an explicit truncation marker.

### Fix B — the receipt is the record, not a log line

Point check 8 at the verdict RECORDS (`pr-*.verdict.json` carrying
`"engine": "codex"`), honouring `KIPI_STATE_DIR`. Already true on disk:
`pr-34.verdict.json` and `pr-46.verdict.json` both carry `"engine": "codex"`.
This is also the founder's own stated definition of the proof, and it matches
the file's own principle: read the record, never re-grep the prose.

## Files to touch

- `q-system/.q-system/scripts/pr-verdict-lib.sh` (Fix A: the renderer)
- `q-system/.q-system/scripts/pr-review-agent.sh` (Fix A: the caller at ~627)
- `q-system/.q-system/scripts/test/test-review-comment-body.sh` (Fix A repro)
- `q-system/.q-system/scripts/verify-codex-review-live.sh` (Fix B)

## Acceptance criteria

- [ ] Reproducer fails against pre-fix ref (`KIPI_TEST_REVIEWER_REF=f277389`)
- [ ] Rendered body of the real 519,377 B review is <= 65,536 B
- [ ] Rendered body contains the verdict AND the findings block
- [ ] Negative self-test: raw file fed to the same size assertion FAILS
- [ ] A real comment lands on a real PR (observed via `gh`), not just locally
- [ ] Fix B: verifier reports RECEIPT FOUND against the existing records, and
      NO RECEIPT YET against an empty state dir (both directions proven)

## Patterns to follow (from this repo's own code)

- ONE reader per fact (`pr-verdict-lib.sh` header comment, sp-c0a9dac3)
- Reproducer ref hatch: `KIPI_TEST_REVIEWER_REF` (already used by
  `test-review-tree-guard.sh` case 5)
- Scar-anchored why-comments, never what-comments
