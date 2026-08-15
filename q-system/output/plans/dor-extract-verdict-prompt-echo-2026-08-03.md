# DoR: extract_verdict reads the reviewer's verdict out of the echoed prompt

> **Recovered work-product — a point-in-time snapshot, not current documentation.**
> This file existed only in a dirty checkout and was recovered on 2026-08-05
> (PR #106, ASK-363). Every claim about system state was true at this document's
> own date and may not be true now. In particular, "wired" here means *merged in
> this repository*; whether the RUNNING copy loads it is a separate question that
> `q-system/.q-system/scripts/runtime-plugin-freshness.py` answers, because the
> two came apart for a full day during this very build. Read it as a record of
> what was decided and why, and verify current state against the code.

## The defect

`codex exec` echoes the entire prompt to stdout. The reviewer prompt contains its
own grading rule:

```
- **VERDICT:** decided by THIS RULE, not by feel:
    - any blocker or major finding      => REQUEST CHANGES
```

`extract_verdict()` anchors on the first line matching `VERDICT` and takes the
first verdict token in the next 3 lines (`head -1`). In every codex review that
first match is the echoed grading rule, so it returns **REQUEST CHANGES** no
matter what the reviewer concluded.

Measured 2026-08-03: **40 of 46** codex-engine verdict records carry
`stated = REQUEST CHANGES`.

Clean proof on PR #91 round 3:

| | |
|---|---|
| first `VERDICT` match | line 121, the echoed prompt's grading rule |
| reviewer's own answer | line 4402, `VERDICT: APPROVE` |
| `extract_verdict` | `REQUEST CHANGES` |
| `verdict_from_findings` | `APPROVE` (empty findings block, reviewer found nothing) |
| recorded / posted | `REQUEST CHANGES` -> `kipi/reviewer-approved=failure` |

## Why it is urgent now

On its own this was mostly latent: before ASK-312, `VERDICT="$DERIVED_VERDICT"`
unconditionally, so the derived value won and the poisoned `stated` was only
recorded, not acted on.

ASK-312 (PR #89, merged 2415fcd) changed that to
`resolve_verdict "$STATED" "$DERIVED"`, which takes the **harsher**. That fix is
correct and should stay. But combined with this bug it means:

> every codex-reviewed PR is now held at REQUEST CHANGES regardless of what the
> reviewer actually said.

`kipi/reviewer-approved` is a required context on `main`, so this blocks the
entire merge pipeline. PR #91 has been through three rounds and cannot go green.

This is not a regression *in* ASK-312; it is a pre-existing bug that ASK-312
promoted from cosmetic to blocking.

## The fix direction (not prescriptive)

`findings_block()` already solved the same problem for its own marker and wrote
down the reasoning: **LAST, NOT FIRST** — the echoed prompt arrives BEFORE the
model's answer, so the last complete occurrence is the real one. `extract_verdict`
should take the reviewer's LAST verdict statement, not the first.

Do not simply swap `head -1` for `tail -1` without reading that function's scars:
the `head -1` there is load-bearing for a *different* real payload (`**REQUEST
CHANGES** (not BLOCK -- ...)`, PR #11 round 4), where the verdict is stated first
and qualified after. Those are two different axes — which BLOCK of text, and which
token WITHIN a line — and the fix must keep the second while fixing the first.

## Acceptance criteria

- [ ] A reproducer using the REAL captured PR #91 round 3 payload (scrubbed of the
      founder home path and any skill bodies, per ASK-345) asserts
      `extract_verdict` returns `APPROVE`.
- [ ] It fails against the current `pr-verdict-lib.sh` via the `REPRO_REF` hatch
      and passes after.
- [ ] The PR #11 round-4 qualified-verdict case (`**REQUEST CHANGES** (not BLOCK
      -- ...)`) still returns `REQUEST CHANGES`. Both cases in one file.
- [ ] A case where the review states NO verdict still returns empty, so unstated
      keeps holding the PR.
- [ ] Mutation: reverting to the first-match form makes the #91 case go red;
      taking the last TOKEN on the line instead of the last BLOCK makes the #11
      case go red.
- [ ] Re-run the sweep over all verdict records and report how many `stated`
      values change, so the blast radius is measured and not assumed.

## Allowed files

- `q-system/.q-system/scripts/pr-verdict-lib.sh`
- `q-system/.q-system/scripts/test/test-severity-floor.sh` (or a new paired test)
- `q-system/.q-system/scripts/test/fixtures/pr-verdict/` (new fixture)
- `q-system/.q-system/capability-manifest.json`

## Out of scope

- Reverting or weakening `resolve_verdict` (ASK-312). It is correct.
- Re-reviewing the 11 merged PRs whose reviews never ran (`sp-c19bca55`).
- Suppressing the prompt echo in `codex exec`. Worth doing, different issue, and
  the parser must be robust to an echo regardless.
