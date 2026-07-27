# Build brief: agents work the Linear board autonomously, in parallel

Paste this whole file into a fresh session. Written 2026-07-27 after a session that
shipped 8 PRs through the loop and watched it fail in six specific ways.

## The goal

Agents pick up Linear issues and work them in parallel, without the founder in the
loop. Parallel *authoring* already works — PR #14 landed today and ASK-208/ASK-209
converged side by side the same evening. Everything below is what stands between that
and letting it run unattended.

## Two standing rules that shape every decision here

1. **Sana decides whether an issue should be worked.** Triage is an engineering call,
   not a founder call. Do not build a design that waits for the founder to label,
   approve, or prioritise anything.
2. **The founder does not review code.** Any design whose terminal state is "waits on
   founder review" is not finished. See problem 6 — this is currently unowned and it is
   the single biggest hole.

## The six problems, with evidence

Each was observed live on 2026-07-27, not theorised. Spillover ids are in
`.prd-os/spillover.jsonl`.

### 1. The worker never fetches — `sp-28ced3d6`

`linear-worker.sh` contains no `git fetch` anywhere. Line 231 creates every worktree
from whatever local `origin/main` ref happens to exist:

```bash
git -C "$SKEL" worktree add -q -B "$BRANCH" "$TREE" origin/main
```

**Observed:** ASK-150 was dispatched to resolve a merge conflict, merged `3b60af0`, and
the conflict survived — `main` was already `72c782d`. The agent did the right thing to
the wrong target and two rounds were wasted.

**Trap, from the review of the first attempt at this fix:** a `git fetch` failure
stopped the whole run with **exit 0** and no Slack, so a dead credential looked
identical to a healthy no-op. Whatever fixes this must page on fetch failure and exit
non-zero. Do not reintroduce the silent path.

### 2. The rework gate ignores mergeability — `sp-71b63e62`

`linear-worker.sh:187-205` via `rework_gate` (`pr-verdict-lib.sh:77`) decides "is there
work to do" from the stored PR verdict alone. An approved PR that *later* stops being
mergeable is invisible.

**Observed:** PR #11 was approved 06:08Z. PR #16 landed 17:30Z and broke it. Both
`converge` and a direct worker run skipped it in **under 2 seconds** as "waiting on
founder merge only". The loop could not dispatch the one thing blocking the merge.

**Trap:** making APPROVE non-terminal needs a round cap, or an unresolvable conflict
yields unbounded rework rounds and permanent Linear comments.

### 3. A crashed reviewer reaches nobody — `sp-3a0cac1c`

`linear-worker.sh:430` logs `"no verdict recorded for PR #N -- review may have died"`
to a file and does nothing else. `slack-notify.sh` is invoked exactly **once** in the
entire worker (line 364, stuck-after-max-attempts).

With no verdict record the PR then hits `rework_gate` = 20 on every later run —
`"skip: has no recorded review verdict"`, `continue` — and the worker still exits 0
(line 447). The PR becomes permanently un-dispatchable and the only trace is one
repeated line in a log nobody opens.

**Unattended, this is the difference between "the run was quiet" and "the run died at
2am."** Fix it before any unattended pilot, or the pilot teaches you nothing.

### 4. No integration — parallel authoring works, parallel landing does not

This is the real gate, and it is not a small fix.

**Observed:** six PRs authored in isolation today. Five merged clean. The sixth (#11)
touched `fleet-health-daily.py`, same as #16. Once #16 landed, #11 could not, and the
loop had no answer — it reported "waiting on founder merge" and went quiet. One
collision in six required a human to diagnose, hand-inject a review, then close and
re-file the work.

Run 55 issues and you get a pile of mutually-conflicting approved PRs that nothing can
land, and no way to see which.

**Do not build a post-hoc conflict resolver.** That is what failed. Refuse to create the
collision instead:

> Before dispatching an issue, compare its DoR `**Files:**` list against every in-flight
> issue. Overlap → it waits. Disjoint → it runs.

The structure already exists. Measured 2026-07-27 across 60 open issues:

```
43 carry a Definition of Ready
40 of those declare an explicit **Files:** list
```

So ~93% of ready issues already state what they would touch. Issues with no declared
files are exactly the ones that should not auto-dispatch. Today's #11/#16 collision
would have been refused at dispatch rather than discovered after both were approved.

**Open question for Sana:** the `**Files:**` list is a human-written estimate. Decide
whether a run that touches a file outside its declared set is a hard failure, a warning,
or an automatic re-declaration — and pin the choice with a test.

### 5. Triage — 55 "ready" issues, most of them nobody asked for

```
worker: 55 ready issue(s) (owner:sana, has a DoR, not owner:assaf)
```

The current filter is a *readiness* flag, not a *worth-doing* flag. Roughly 44 of those
were filed automatically by scanners (`fleet-health`, `launchd-health`) — inflow is
automated, outflow is manual, so the board only grows.

**Sana owns this call.** Build a triage step that decides what deserves a run and what
gets closed, merged into a sibling, or parked with a reason. Requirements:

- Every decision is recorded on the issue, so the reasoning survives.
- It is reversible and auditable — no silent deletion.
- It runs before dispatch, not as a side effect of dispatch.
- A scanner-filed issue is not automatically worth working *or* automatically junk.
  Volume from one detector is a signal about the detector.

### 6. The loop terminates at "waits on founder merge", and that step has no owner

`linear-worker.sh:14,342` instructs the agent: *"DO NOT MERGE. DO NOT close the issue —
closeout runs through /issue-verify and /issue-closeout, which refuse without
receipts."* That separation is deliberate and correct: the thing that writes code should
not be the thing that certifies it.

**But the founder does not review code, and nothing else invokes closeout.** Today 7 PRs
merged with **zero** receipts and no gate noticed — `.prd-os/issues/` has no spec for any
`ASK-*` worked today and `receipts.jsonl` has no matching entry. A human (me) merged all
of them by hand.

**This is the biggest hole and it must be designed, not patched.** Decide who holds
merge authority when the founder is not in the loop, and what evidence is required
before it fires. Constraints:

- `--admin` is not available. Branch protection stays; `validate` stays required.
- The reviewer is already adversarial and produces a machine-readable verdict plus
  findings. That is real evidence — use it.
- Do not let the author merge its own work. The separation in problem 6's first
  paragraph is the point.
- Related in-flight work: **ASK-210** is building a receipt gate so a `sana/ask-*` PR
  cannot merge without a prd-os receipt. Read its outcome before designing this.

## Build order

Problems 1-3 all live in `linear-worker.sh`. **Ship them one issue at a time, never in
parallel** — they would conflict with each other, which is problem 4 in miniature.

```
1. fetch before worktree creation        small
2. mergeability in the rework gate       small
3. crashed reviewer reaches the founder  small
4. file-disjoint dispatch                medium
5. triage step (Sana decides)            medium, judgment-heavy
6. merge authority                       design first, then build
```

Then a **bounded pilot: 3 issues Sana selected, run unattended, measure how many land
with no human touching them.** If 3 land clean, go to 10. A pilot before 1-3 is
worthless because a dead run and a quiet run look identical.

## Scope discipline — the hard lesson from 2026-07-27

One issue = one change. The correlation was unambiguous:

| issue | scope | rounds to converge |
|-------|-------|--------------------|
| ASK-209 | one focused change | **1** |
| ASK-204 | medium | 3 |
| ASK-208 | four fixes, one file | **capped out, closed unmerged** |

ASK-208 bundled problems 1-3 plus the scratch guard into one PR. Findings went
`5 → 3 → 3` — flat, with each round's major newly introduced by the previous round's
fix. Round 3's major (`mark_capped` rebuilding the attempts ledger from `{}` on any
parse failure) would have silently disarmed the very caps that PR added.

That was a scoping failure, not a capability failure. Branch `sana/ask-208` is kept and
its three reviews are at `~/.config/kipi/pr-reviews/pr-22-*.md`. **Read them before
re-filing 1-3 — the work is mostly right, the packaging was wrong.**

## Also outstanding, same neighbourhood

- **`sp-1aae7516`** — the worker commits its own scratch files into PRs. Happened in
  three consecutive PRs (#18, #19, and again in #23's branch). The guard must run at
  **push**, not commit: `--no-verify` bypasses a commit hook and `kipi-update.sh` uses
  that flag routinely. Also do not write `extensions.worktreeConfig` into the founder's
  shared `.git/config` without a cleanup path.
- **`sp-dde4151f`** — Linear reopens a *completed* issue when any new PR merely cites
  its identifier. Observed: ASK-204 went Done → In Progress at 20:03:13Z because PR #21
  mentioned it. This silently un-completes finished work and, since `spillover resolve`
  now verifies closure against Linear, it also blocks the ledger drain.
- **`sp-2ea6e19c`** — five scripts write Linear issues; only the two caught colliding
  were fixed. Two of them rendered different bodies for the same `kipi-key` and Slacked
  "1 updated" twice a day forever on an unchanged fleet.

## The pattern worth fixing structurally

**Silent success appeared three separate times in one day**, each introduced by a fix
for something unrelated: the fetch fix exiting 0 on failure, the `errors` bucket unread
by `launchd-health-check.py`, and `--reset-rounds` writing a phantom ledger key without
validating its input.

There is no gate anywhere in this repo for "a failure path that exits 0 and tells
nobody." Only a human reviewer's attention catches it. A repo-wide check would have
caught all three before review, and is probably worth more than any single item above.

## Ground rules

- No `--admin`, ever. No relaxing branch protection.
- Every fix ships a reproducer shown **RED before the fix and green after**. State the
  command and both outputs.
- A prompt instruction is not enforcement. This repo's `CLAUDE.md` requires a hook,
  test, validator, or required check.
- Do not hand work back to the founder. If the loop cannot dispatch something, fix the
  loop.
