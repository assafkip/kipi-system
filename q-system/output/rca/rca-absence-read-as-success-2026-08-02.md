# RCA: the required review check went green for a review that never ran

**Date:** 2026-08-02
**Trigger:** Sana declined to trust a green `kipi/reviewer-approved` that a coordinator-launched review round had just posted, and read the transcript instead of the status.
**Surface-fix commit:** 5495a9b (PR #76)
**Structural-fix commit:** pending — see Action items

## What happened

`kipi/reviewer-approved` is the single required status check standing in for human
review across this fleet. On PR #74 it went green twice for a reviewer that had
explicitly declined to start.

codex answered *"Reply `OK` and I'll run the review exactly as planned"* and echoed
the reviewing prompt's findings TEMPLATE back: `FINDINGS:`, the column legend,
`END FINDINGS`, zero data rows. `verdict_from_findings` walked its severity ladder,
found no `blocker|`, no `major|`, no `minor|`, and fell through to `else APPROVE`.
`pr-review-agent.sh` then preferred that derived APPROVE over the reviewer's own
STATED `REQUEST CHANGES`, printed a NOTE about the disagreement, and posted
success on the exact head SHA.

| SHA | wall clock | artifact | posted |
|---|---|---|---|
| `73a8870` | ~8 min | 345 KB, 3 rows | `failure / REQUEST CHANGES` |
| `b6af3e0` | ~20 s | 8 KB, 0 rows | `success / APPROVE` |
| `1e4c748` | ~57 s | 38 KB, 0 rows | `success / APPROVE` |

Two sibling instances of the same reading appeared the same night. `codex exec`
returns **rc=0 while printing "out of credits"**, so an exit-code check reads an
outage as a clean run; the state was misread twice before anyone read stdout. And
the earlier `has_complete_findings_block` bug (sp-c0a9dac3) was the same shape one
layer down: a truncated block read as an empty one, and empty released the PR.

## Surface symptom

An open PR carrying unreviewed code showed a green required check on its current
head, indistinguishable to any human or script from a PR a reviewer had approved.

## Surface root cause

`pr-verdict-lib.sh:136`, `else printf 'APPROVE'` — the terminal branch of a
severity ladder that has no case for "there were no severities because there was
no review".

## Structural root cause

type: implicit-contract

Every one of these decisions maps **absence of a negative signal onto a positive
verdict**. An empty severity list, an empty exit code, an empty findings block:
each is silence, and in each case the code read silence as "nothing is wrong"
when it equally meant "nothing was examined".

The two states are byte-identical at the point of the check. "Reviewed, found
nothing" and "never started" produce the same block; "ran cleanly" and "died
before starting" produce the same rc=0. A checker that cannot distinguish them
must not choose the releasing answer — but choosing the releasing answer is the
default, because it is the branch you reach by falling through.

That default is what makes the class dangerous rather than merely wrong. A gate
that fails closed produces a complaint and gets fixed within the hour. A gate that
fails open produces a green check, and its silence is indistinguishable from a
pass, so nothing ever reports it. It was found here only because a person
distrusted a green they had not earned.

## Verification

The three real artifacts replayed through the fixed path, with the fixtures kept
byte for byte rather than reconstructed:

```
real-review-request-changes  stated=REQUEST CHANGES derived=REQUEST CHANGES -> REQUEST CHANGES  posts failure
declined-to-start-short      stated=REQUEST CHANGES derived=APPROVE         -> REQUEST CHANGES  posts failure
declined-to-start-long       stated=REQUEST CHANGES derived=APPROVE         -> REQUEST CHANGES  posts failure
```

Suites, all green:

```
test-review-gate-no-fake-green   16/16
test-findings-block-reader       10/10
test-severity-floor            198/198
```

Mutation-checked: restoring `VERDICT="$DERIVED_VERDICT"` on a copy (validated as
applied and differing) fails 2 of 16, including the call-site wiring check.

## Contributing factors

- **The first fix attempt was wrong and two existing suites caught it.** Making an
  empty block stop deriving APPROVE collided with a deliberate contract —
  `test-severity-floor.sh` pins "an empty findings block must derive APPROVE" by
  name so a round 2 that refutes everything can still land. The discriminator had
  to come from outside the block.
- **The verdict record misattributes the engine** (`sp-39b45387`): it writes the
  CLI-selected engine, so an Opus fallback is recorded as codex. Anyone auditing
  which PRs got independent review would have counted these as codex-reviewed.
- **Blast radius was growing the same evening.** The loop merges its own PRs, and
  the dispatch daily cap went from 3 to 10 hours before this was found.
- **ASK-213 already exists** for the sibling class ("failure paths that exit 0 and
  tell nobody") and had not been built.

## Fixes shipped

- `resolve_verdict()` in `pr-verdict-lib.sh`: ranks the verdicts and takes the
  harsher of stated and derived, so a disagreement can never resolve toward
  approval. The severity floor still overrides a reviewer that logs a blocker then
  writes APPROVE; silence can no longer overrule a reviewer that said stop.
- `pr-review-agent.sh` routes through it instead of assigning the derived verdict.
- `test-review-gate-no-fake-green.sh`, fixtures = the three real artifacts.
- Memory corrected: probe codex with a real billed call and read the OUTPUT, since
  the rc is 0 either way.

## Action items

- [ ] Build ASK-213's checker and scope it to this class explicitly: a repo-wide
      audit for a **releasing outcome derived from an empty or absent input** —
      `else APPROVE`-shaped terminal branches, `rc==0` treated as success where
      the tool is known to exit 0 on failure, and empty-collection defaults that
      return a permissive value. Owner: Sana.
- [ ] Add a `verdict_rank`-style floor wherever else two independent signals are
      reconciled in this fleet; enumerate those sites first with a grep and paste
      the list into the issue rather than asserting a count. Owner: Sana.
- [ ] Fix `sp-39b45387` so the verdict record names the engine that actually ran.
      An audit of "which PRs got decorrelated review" is worthless until it does.
      Owner: Sana.
- [ ] Add a `codex exec` wrapper that inspects stdout for the credit-exhaustion
      string and returns non-zero, so no caller has to remember the rc lies.
      Owner: Sana.

## Lessons

- Silence is not consent. When two states produce identical bytes at the point of
  a check, the checker must take the non-releasing branch, not the one it reaches
  by falling through.
- A gate that fails open is worse than no gate: it produces a green nobody
  re-examines, so it also removes the suspicion that would have found it.
- The exit code is not the result. Read what the tool printed, especially for a
  tool observed to exit 0 while announcing its own failure.
