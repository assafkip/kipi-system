# Fixtures: the two PR #165 reviews that disagree about which tree they read

Both files are reviewer output from `pr-review-agent.sh` runs on
`assafkip/kipi-system` PR #165, 2026-08-14 PT. Both runs were invoked for the
same head sha, `c87245b06e0f2c9e0c4b7a1d3f5e8a2b9c6d4e10`. Only one of them read
that commit. That disagreement is the whole ASK-830 defect, and it is why these
two files are the fixture pair: nothing about the invocation distinguishes them,
only their content does.

| File | Producing run | What it read |
|---|---|---|
| `pr-165-round2-wrong-tree.md` | `codex/assafkip_kipi-system__pr-165-20260814-172717.md` (173,163 bytes on disk) | `0880859e`, the merge-base from BEFORE the fixes under review |
| `pr-165-round3-right-tree.md` | `codex/assafkip_kipi-system__pr-165-20260814-173102.md` (253,197 bytes on disk) | `c87245b0`, the commit it was invoked for |

## How they were retrieved, precisely

These are NOT copies of the on-disk review files. Those live under
`~/.config/kipi/pr-reviews/codex/`, outside the project directory, and the
harness this work ran under refuses to read that path. Say that plainly rather
than implying a copy that did not happen.

What is here instead is the same producer's output retrieved through the channel
`pr-review-agent.sh` itself publishes it on: the rendered review comment the
wrapper posted to PR #165 for each of those two runs, read back with

```bash
gh pr view 165 --repo assafkip/kipi-system --json comments
```

Each comment is produced by `review_comment_body()` from the review file named in
its own first lines, and carries that review's verdict header, its findings block
byte-for-byte from `findings_block()`, and the trailing ~55 KB of the reviewer's
own output verbatim. Comment index 1 is the 172717 run, index 2 the 173102 run;
each names its source path in the body, which is how the mapping above was made
rather than by timestamp arithmetic.

## What this costs, and why it is still the right fixture

The rendered comment is a TAIL. Facts present in the full 173 KB file but outside
the last 55 KB are absent here:

- The round-3 file mentions `c87245b0` three times; the retrieved tail mentions
  it zero times. That is why the guard is written as "refuses a review that
  declares a DIFFERENT tree", never "requires a review that names the head sha" —
  the latter would pass round 2 anyway (its body also carries `c87245b0`) and
  would fail round 3's tail for a reason that has nothing to do with the defect.

  **The first version of this file drew a second conclusion from that fact, and
  it was wrong** (PR #197 round 2, major 2). It read the tail's silence as making
  round 3 a sufficient NEGATIVE SELF-TEST. It is not: a fixture that declares no
  tree is, to this guard, byte-equivalent to case 3's empty review, so case 2
  never reaches the head-sha exemption at all. Measured — with that exemption
  deleted, so the guard refuses every review naming any tree, the suite still
  reported `PASS (10 checks)`. The negative self-test is now case 5, whose body
  runs `git show <head>:<path>`, and case 5m mutates the exemption away and
  requires case 5 to go red. Round 3 stays as the "declares nothing" case it
  actually is.
- The round-2 tail still carries every signal the guard keys on: 13 occurrences
  of `0880859e`, its `git show 0880859e:fleet-unblock.py` reproducers, and the
  sentence "GitHub was also unreachable, so the review used the locally available
  PR tip `0880859e`".

`test-review-analysed-tree.sh` asserts both of those properties before it runs a
single case, so a fixture that silently lost them fails as a broken premise
instead of passing as a working guard.

## pr-197-round4-quotes-the-diff.md

The round-4 adversarial review OF THIS CHANGE, posted to PR #197 on 2026-08-16,
copied verbatim from `gh pr view 197 --json comments` (the rendered comment, same
caveat as the two files above: it is the comment, not the on-disk review).

It is here because the guard REFUSED IT. Measured before the fix:

```
$ bash .ask830-probe.sh .ask830-round4-review.md
REFUSE (0880859e)
```

That is not a hypothetical residual. This review's job was to critique the guard,
so it cites the `git show 0880859e:...` lines the change adds — and the guard
read those citations as commands it had run. A required check that eats the
review of its own PR wedges every later round. Case 17 pins it.

Its value as a fixture is exactly that nobody wrote it to be one: it is a real
reviewer's real prose, so the quote shapes in it (inline code mid-sentence, a
double-backtick span, a sha in parentheses) are what reviewers actually emit
rather than what I would have guessed they emit.
