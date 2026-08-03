# RCA: a mechanism's existence is counted as coverage, and nothing reconciles declared against observed

**Date:** 2026-08-02
**Trigger:** PR #75 (ASK-311) would not merge. Diagnosing why surfaced a cluster of seven observations from one session.
**Issue:** ASK-313
**Surface-fix commit:** see ASK-313 branch `sana/ask-313`
**Structural-fix commit:** same

## What happened

ASK-311 shipped on `sana/ask-311` and was opened as PR #75 with auto-merge armed.
It never merged. Measured 2026-08-02:

```
$ gh pr view 75 --json mergeStateStatus,autoMergeRequest
  mergeStateStatus = BLOCKED, autoMergeRequest = enabled (SQUASH)
$ gh api repos/assafkip/kipi-system/branches/main/protection
  required_status_checks.contexts = ["validate","kipi/reviewer-approved"]
$ gh pr checks 75
  validate  pass
  (kipi/reviewer-approved absent -- not listed at all)
```

`kipi/reviewer-approved` is REQUIRED on every PR to `main`. Its only producer is
`pr-review-agent.sh`. That script's only automated caller is
`linear-worker.sh:1802`, reachable only from the dispatcher loop
(`com.kipi.dispatch.plist`, 900s) for a DoR-ready issue it picked. No GitHub
Actions workflow posts it; `validate.yml` is the only workflow in the repo.

So a PR opened by any path other than the dispatcher carries a required check
with no producer. Auto-merge was armed and correctly refusing. Nothing alerted.

## Surface symptom

Seven observations were collected. They are not one incident, and separating
them was the first job.

| # | Observation | In the class? |
|---|---|---|
| 1 | `kipi/reviewer-approved` required with no producer for most PRs (`sp-59de96e9`) | **yes** |
| 2 | "auto-merge is armed, it will land on its own" — asserted from a partial read | yes, reporting layer |
| 3 | Memory index asserted "Codex OUT of credits", refuted by a real billed call | yes, reporting layer |
| 4 | `capability-gate.py:422` runs a pytest module as `python3 <file>`; 0 tests collected, exit 0, counted as covered (`sp-c2b64f9b`) | **yes** |
| 5 | ASK-311 made `test_token_guard.py` bill real Fable calls (0.7s to 60.9s); caught only by running a neighbouring suite | **yes** |
| 6 | `rca-specification-reported-as-state-2026-08-02.md` — 9 false claims, each substituting a specification for an observation | yes, this class stated epistemically |
| 7 | Merge conflict in `capability-manifest.json` with a concurrent ASK-122 session | **no** |

### Why #7 is not in the class (decided with evidence, not assumed)

`capability-manifest.json` is a structured JSON object whose `expected_tests` is
a 109-entry list, not an append-only ledger. Two branches each appending an
entry conflict textually. Two facts rule it out of the class:

- **git refused loudly.** Every other observation here is a *silent* wrong
  answer. A conflict marker is the inverse failure mode: maximum visibility, no
  false confidence. Nothing was reported as covered when it was not.
- **The fleet's own precedent does not extend.** `.gitattributes` sets
  `merge=union` on `.prd-os/receipts.jsonl` precisely because it is append-only
  line data. Union on a JSON array produces invalid JSON, so the existing remedy
  is not applicable and its absence here is correct, not an oversight.

#7 is ordinary concurrency cost. It is real and it recurs, but it is a different
problem with a different fix, and bundling it would have hidden both.

## This class was already named, EARLIER THE SAME DAY

The most important finding here is not the class. It is that the class was
already written down before this incident was diagnosed, and the recurrence
happened anyway.

Commit `e0353b7` (ASK-312, 2026-08-02, ~4 hours before this) shipped five RCAs
and named the common structure directly:

> each is a claim of coverage that nothing enumerates, failing in the direction
> that looks like success

with `absence-read-as-success` as one of its five classes — including the
required review gate itself. The sibling RCA is
`q-system/output/rca/rca-absence-read-as-success-2026-08-02.md`.

So the hypothesis this investigation was asked to test was correct AND already
recorded. What that means for the fix matters:

- **Naming a class does not enumerate its instances.** The ASK-312 write-up
  found `absence-read-as-success` in the review gate's *verdict logic* (a green
  posted for a review that never ran) and fixed it there, in `resolve_verdict`.
  The same class in the same file's *delivery* path — the status never posted at
  all — was not enumerated, because nothing enumerates. Each instance was found
  by tripping over it.
- Its action item list names the `rc==0`-treated-as-success shape, which is
  observation #4 (`sp-c2b64f9b`). That is already owned there and is not
  re-litigated here.

The corrective this RCA adds is therefore not another description of the class.
It is one executable reconciliation in one domain that had none, plus the honest
statement that the other domains still have none.

## Surface root cause

`kipi/reviewer-approved` has one producer on one code path. That is a wiring
gap, and on its own it would be a one-line fix.

## Structural root cause

### Root cause 1 — the sweep can only see what was POSTED (latent-defect)

`ci-redrive.py` already sweeps every open PR every 900s. But `failing_checks()`
iterates `statusCheckRollup`, so it can only observe contexts that exist. **An
absent required context contributes zero rollup entries.** Every reader built on
the rollup therefore reads a wedged PR as perfectly healthy. The sweep was not
misconfigured; it was structurally incapable of seeing absence.

This is the same shape as #4. `capability-gate.py:422` invokes a declared test
and counts `ran += 1` on exit 0. A pytest-only module collects zero tests and
exits 0. The gate observed an exit code and reported coverage.

Both count the EXISTENCE or the EXIT CODE of a mechanism as evidence that the
mechanism did its job. Neither reconciles what is DECLARED to be covered against
what was OBSERVED to run.

### Root cause 2 — the fleet already solved this once, in one domain only (latent-defect)

The 2026-07-23 silent-absence capability gate was built on exactly the right
idea: *diff declared-vs-actual, both directions.* Its own comment in
`validate.yml` says so — "it discovers every test artifact by convention, diffs
declared-vs-actual BOTH directions."

That principle was applied to test artifacts and to nothing else. Required
status checks are a declared-coverage set with an observable actual set, and no
one diffed them. **The coverage boundary of that gate is a boundary nobody
wrote down**, so its silence on PR #75 read as reassurance.

### Root cause 3 — the tooling actively misreports this state (environmental-trigger)

`gh pr checks 75` printed `validate pass` and did not mention
`kipi/reviewer-approved` at all. This is a known, still-open GitHub CLI defect:
[cli/cli#6448](https://github.com/cli/cli/issues/6448) — `gh pr checks` and
`gh pr status` report success while a required check sits in `Expected`, because
the CLI does not surface expected-but-unreported contexts.

This is load-bearing for #2 and it is why #2 is not simply carelessness. The
cheap check was one keystroke away and returned a wrong answer; the correct
check (`gh api .../branches/main/protection` plus a set-diff) is four times
longer and nobody had written it. That is the same finding as the 2026-08-02
specification-vs-state RCA, root cause 1: *the cheap check and the correct check
are different checks, and only the cheap one is at hand.*

### Root cause 4 — a new outbound call retroactively arms every older suite (latent-defect)

#5 is the same class one layer down. ASK-311 added an outbound call to shared
code, which put a pre-existing suite (`test_token_guard.py`) on a live billing
path. The suite was declared covered, ran, and passed. Nothing measured that
what it exercised had changed underneath it. It was caught by running a
neighbouring suite by hand, which is not a mechanism.

## Prior art: is this solved elsewhere?

Researched 2026-08-02 with sources.

**Yes for the general footgun, no for this shape.**

- GitHub documents the deadlock:
  [Troubleshooting required status checks](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/collaborating-on-repositories-with-code-quality-features/troubleshooting-required-status-checks)
  — "the pull request is blocked with 'Waiting for status to be reported'",
  "Associated checks stay in a 'Pending' state and block merging". There is no
  timeout and no alert. Absent is not failed.
- The classic remedy is an inverse-filter twin workflow posting the same context
  green ([GHES 3.2 archived docs](https://docs.github.com/en/enterprise-server@3.2/repositories/configuring-branches-and-merges-in-your-repository/defining-the-mergeability-of-pull-requests/troubleshooting-required-status-checks)),
  or an always-running aggregator
  ([re-actors/alls-green](https://github.com/re-actors/alls-green),
  [Mergify ci-gate](https://docs.mergify.com/monorepo-ci/github-actions/)). The
  recipe was quietly dropped from current docs; the replacement ask
  ([community #142210](https://github.com/orgs/community/discussions/142210))
  has zero answers.

**The standard fix does not fit this fleet, and applying it would have made
things worse.** Two independent reasons:

1. Absence of `kipi/reviewer-approved` is a *correct refusal*, not a
   misconfiguration. `linear-worker.sh:687` states the blast radius: "Remove
   `kipi/reviewer-approved` from that set and this becomes an unreviewed-merge
   machine." A job that always posts it green converts a review gate into
   decoration on a repo that fans out fleet-wide through `kipi update`.
2. GitHub requires **both** when a check run and a commit status share a name —
   "If a check and a commit status have the same name, both must pass when that
   name is required." `kipi/reviewer-approved` is a legacy Commit Status, so an
   Actions job named after it would *add* a second thing to satisfy and deepen
   the deadlock.

**On detection there is no off-the-shelf art at all.** `mergeStateStatus:
BLOCKED` does not say what is blocking
([cli/cli#10775](https://github.com/cli/cli/issues/10775)); a request for a
mergeability-evaluation endpoint is unanswered
([community #162462](https://github.com/orgs/community/discussions/162462)).
The only workable approach found is the one built here: read required contexts
from the protection API, set-diff against the contexts posted on the head, and
act where the diff is non-empty and nothing is failing.

## The fix

`ci-redrive.py` gains a `wedged` tier. It does **not** fake the status; it finds
the wedge and hands the PR to the real producer.

- `required_contexts(repo_dir, branch)` reads branch protection, both the legacy
  `contexts` half and the `checks` half.
- `posted_contexts(pr)` reads every context name on the head regardless of
  state. A required context posted and FAILING is a reviewed-and-rejected PR —
  a visible state with its own consumer — not a wedge.
- `wedged_candidates()` diffs them. Not filtered by `attribute()`: branch
  protection does not care who pushed, and the founder's own PR is the one class
  with no agent to hand it back to.
- `kipi-dispatch.sh` runs `pr-review-agent.sh` on one wedged PR per heartbeat,
  detached, bounded by the same attempts ledger the redrive tier uses.

Placement detail that matters: the block sits **above** the `nothing ready`
early exit. A wedge is most likely exactly when no issue is ready — the issue is
done, the PR is open, the board is quiet.

### Two defects the live run found in the fix itself

1. **404 and 403 are different answers.** Version 1 raised on any non-zero rc,
   reasoning that `repo-preflight.sh` already refuses unprotected repos. That is
   a claim about the DEFAULT branch; this asks about each PR's BASE branch. The
   first live run died on it:
   `could not read branch protection for sana/block-expiry (rc 1): gh: Branch
   not protected (HTTP 404)` — rc 2, entire sweep dead. A stacked PR is ordinary
   here, and one unprotected base reintroduced the exact silence the detector
   exists to end. 404 is now definite (nothing required, cannot wedge); 403
   stays indefinite.
2. **Red CI outranks a wedge.** Real PR #76 was both red on `validate` and
   missing the required context. Reviewing a PR whose build is broken buys a
   codex read of a tree about to change. The redrive tier owns it until CI is
   green.

Both were found by running against the real repo, not by reasoning. Neither
would have been caught by the fixture suite as first written.

## Verification

Reproducer: `q-system/.q-system/scripts/test/test-wedged-pr.sh`, registered in
`capability-manifest.json` so it runs in CI.

```
before the fix:  wedged-pr:  6 passed, 15 failed
after  the fix:  wedged-pr: 34 passed,  0 failed
```

The 6 that "passed" before were false passes — argparse exits 2 on an unknown
op, which trivially satisfied the rc-2 and prints-nothing assertions. That is
why the suite was mutation-tested rather than trusted:

| Mutant | Killed by |
|---|---|
| unreadable protection reads as empty | 4a |
| a FAILING required context counts as absent | 3a |
| drafts included | 6a |
| agent branches only (founder PR dropped) | 7a |
| ledger cap ignored | 5c |
| drop the legacy `contexts` half | 9a |
| drop the `checks` half | 10a |
| 404 treated as indefinite | 11a |
| all failures treated as empty | 12a |
| red-CI precedence removed | 13a |

10 of 10 killed. Cases 9 and 10 exist **because** mutation found nothing: with
both protection halves populated (what GitHub sends today) a reader of either
one passed every case, so "both halves are read" was an unpinned claim.

Verified against the live repo, not a simulation. Ground truth from
`gh pr checks` / the statuses API on 4 real PRs:

| PR | posted statuses | detector |
|---|---|---|
| #75 | `kipi/reviewer-approved` (failure) | correctly NOT wedged |
| #76 | none, `validate` FAILING | correctly deferred to redrive |
| #68 | none, `validate` passing | correctly offered to the reviewer |
| #77 | none, converge live for ASK-288 | correctly skipped |

## Found while verifying: a test suite on a live, billed path (`sp-c5f09ad2`)

Running the repo's own gate suite locally to check this change surfaced a
separate instance of the same class, confirmed by process tree rather than by
reading:

```
capability-gate.py                       <- the CI gate
  test-severity-floor.sh
    linear-worker.sh --apply --issue ...  <- the REAL worker
      pr-review-agent.sh 808 --issue ...  <- the REAL reviewer
        codex exec --model gpt-5.6-sol -C /Users/.../wt/ask-313
```

That last line is a real, billed codex call, pointed at the working tree, from a
test. `pr-review-agent.sh 901 --post` was also observed in the process table the
same evening. The suite is quiet in CI only because the runner has no codex
credentials — an accidental shield, not isolation. The fable-discipline lint
exists to block exactly this and did not see it, because the live call is three
processes below the line the test actually writes.

Not fixed here (it is a different file, a different owner, and a fix would be
scope creep on a data path already known to be delicate). The billed processes
were killed; the finding is captured as `sp-c5f09ad2`.

It is listed in this RCA rather than only in the ledger because it is the
cleanest available demonstration of the class: a gate whose silence was trusted,
which was not doing the isolating everyone assumed it was.

## Action items

- [x] Reproducer written and shown failing before the fix (ASK-313)
- [x] `wedged` tier in `ci-redrive.py`, wired from `kipi-dispatch.sh` (ASK-313)
- [x] Test registered in `capability-manifest.json` so it runs in CI (ASK-313)
- [x] Verified against real PRs #75/#76/#68/#77 (ASK-313)
- [x] `sp-c5f09ad2` captured: `test-severity-floor.sh` passes `--post` through
      `"$@"` to a live-capable reviewer; confirm the isolation is a stubbed seam
      and not an accidental shield
- [ ] `sp-c2b64f9b`: `capability-gate.py:422` must distinguish "ran and asserted"
      from "exited 0". NOT re-owned here — it is already action item 1 of
      `rca-absence-read-as-success-2026-08-02.md` ("`rc==0` treated as success
      where the tool is known to exit 0 on failure"). Left open against that
      item so one fix serves both; duplicating it would split one decision
      across two tickets, which is the failure ASK-122 already paid for
- [ ] No mechanism yet measures root cause 4 (a new outbound call arming older
      suites). `PYTEST_CURRENT_TEST`-keyed chokepoint refusal exists for the
      ASK-311 path only; generalising it is not in this issue

## What is deliberately left open

- **The producer is still local-only.** A launchd job on one Mac is the sole
  producer of a GitHub-side required check. If that Mac is off, PRs wedge; they
  are now *detected and paged* rather than silent, but not produced. Moving the
  producer into Actions is a real option and a much larger blast radius (it
  needs codex credentials in CI), so it is not bundled here.
- **No separate spend lane** for wedged reviews. The ceiling is the number of
  open PRs, once each per missing-context set — bounded, but it does not draw
  from `KIPI_DISPATCH_DAILY_MAX`.
- **#7 (the manifest conflict)** is untouched by design, per the decomposition
  above.

## Cause-type tags

`latent-defect` (root causes 1, 2, 4) · `environmental-trigger` (root cause 3,
the `gh pr checks` misreport) · not `human-error`: the cheap check returned a
wrong answer and the correct check did not exist.
