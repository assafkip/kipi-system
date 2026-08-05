# Judgment: is the current approach the right one?

> **Recovered work-product — a point-in-time snapshot, not current documentation.**
> This file existed only in a dirty checkout and was recovered on 2026-08-05
> (PR #106, ASK-363). Every claim about system state was true at this document's
> own date and may not be true now. In particular, "wired" here means *merged in
> this repository*; whether the RUNNING copy loads it is a separate question that
> `q-system/.q-system/scripts/runtime-plugin-freshness.py` answers, because the
> two came apart for a full day during this very build. Read it as a record of
> what was decided and why, and verify current state against the code.

Written 2026-07-30 by an outside reader, from artifacts only. No prior-session
summaries were read.

## Verdict in one line

The approach is right, the code is finished, and the accumulated work should NOT
be discarded. The artifact is missing for a reason that lives nowhere in the
review path: since the last piece of review wiring landed, the dispatcher has not
once picked an issue that produces a diff.

## What I verified, and how

Counts below were produced by a command before being written down.

| Claim | Command | Result |
|---|---|---|
| verdict records on disk | `for f in *.verdict.json` | 35 |
| carry `engine` | same loop, read the key | 3 (PR 34, 46, 47) |
| carry `invoker` | same loop | 1 (PR 47, `manual`) |
| carry `invoker=worker` | same loop | **0** |
| dispatcher dispatches ever | `grep -c 'dispatched ASK' dispatch.log` | 14 |
| ready issues right now | `bash ./kipi work` | 29, top pick ASK-148 |

## The chain is already wired end to end

Every link exists in the checkout the launchd job runs.

- `~/Library/LaunchAgents/com.kipi.dispatch.plist` sets
  `KIPI_REPO=/Users/assafkipnis/projects/kipi-system`, so the loaded job runs the
  main checkout on `main`.
- `kipi-dispatch.sh:313` picks work; `:393-406` launches
  `./kipi converge --issue <N>` in a new session.
- `linear-worker.sh:1156` runs the reviewer as
  `KIPI_REVIEW_INVOKER=worker $REVIEWER_CMD "$PR_NUM" --issue "$ISSUE" --post --engine codex`
- `pr-review-agent.sh:137` reads `INVOKER="${KIPI_REVIEW_INVOKER:-manual}"`;
  `:649-657` writes it into the record next to `engine`.
- `test-review-invoker-provenance.sh` runs green, 7/7, including the fail-safe
  case (an unlabelled run must not read as dispatcher-driven).

There is no missing code between the dispatcher and the verdict file.

### The producer census, run properly

`q-system/lessons/a-gate-is-only-real-if-production-writes-what-it-reads.md` says
a gate is fake when only tests write the field it reads. I ran that census.
`invoker` appears in exactly four places in the real tree: the reviewer that
writes it (`pr-review-agent.sh`), the verifier that reads it
(`verify-codex-review-live.sh`), the test, and the worker call site
(`linear-worker.sh:1156`). The worker is a genuine non-test producer, so the
contract is fulfilled **in code**.

What is unfulfilled is narrower and worth stating exactly: **the producing line
has never executed in production.** Not because it is unreachable, but because
control has not reached it since it was written. That is a different disease from
the one the lesson describes, and it takes a different cure: not another edit,
one successful run.

## Why the artifact does not exist (over-determined, three reasons)

**1. The codex switch is newer than every reviewed dispatcher run.**
`--engine codex` reached the worker call site in `42c2995`, 2026-07-29 15:18
local (22:18Z). Two dispatcher-driven runs had already opened PRs and recorded
verdicts before that:

- ASK-218 to PR #42, `pr-42.verdict.json` ts 2026-07-29T16:31:01Z,
  `converge-ASK-218.log` DONE exit-1, four rounds, APPROVE WITH NITS.
- ASK-223 to PR #40, `pr-40.verdict.json` ts 2026-07-28T19:09:55Z,
  `converge-ASK-223.log` STOP exit-2 at the round cap, REQUEST CHANGES.

Both were reviewed with nobody at the keyboard. Both used the Claude reviewer,
and neither record carries `engine` or `invoker` because those fields did not
exist yet.

This matters more than it looks. **The unattended dispatch-to-review loop has
already run to completion twice.** What was never proven is that same loop with
codex named in the record. The remaining gap is two provenance fields on a
behaviour that already happened.

**2. The invoker field is newer still, and is local-only.**
`a215e5e`, 2026-07-30 10:37 local (17:37Z).
`git merge-base --is-ancestor a215e5e origin/main` says no: it is one of 33
unpushed commits on local `main`. The branch `sana/ask-221-invoker-only` at
`c37d41b` is that same change isolated on top of `origin/main`, and is 33 commits
behind local main.

Practical consequence: **the branch is not on the path to the artifact.** The
launchd job runs the local checkout, which already carries the field. The branch
is how `origin/main` becomes correct, which is a real but separate goal.

**3. Since both landed, every dispatch has produced no PR.**
Four dispatcher-driven runs after the wiring completed, all identical
(`converge-ASK-149.log`, `converge-ASK-148.log`):

```
STOP exit-7: no PR on sana/ask-149 after round 1 (worker rc=0)
```

`linear-worker.log:4248`, ASK-149: "BLOCKED. ASK-149's DoR is sound but not
executable by this session. No code change, so no PR exists."
`linear-worker.log:4423`, ASK-148: "stopped at the DoR. Not achievable as
written. Nothing committed, no PR, there's no diff to ship."

Those refusals read as correct engineering. The defect sits upstream of Sana: the
picker has no notion of "will this yield a diff", and `ready()` cannot tell an
executable spec from an unexecutable one.

## What repeats tomorrow morning

`bash ./kipi work` right now:

```
worker: 29 ready issue(s) (owner:sana, has a DoR, not owner:assaf)
[dry] would work ASK-148 (attempt 1/3)
```

ASK-148 is the issue Sana declared unexecutable today. At 07:00 local the budget
refills and slot 1 of 3 goes to it again. She removed ASK-149 from the pool by
relabelling it `owner:assaf` (`linear-worker.log:4392-4393`, showing
`ready(ASK-149)` flip True to False). ASK-148 got no such treatment; her closing
line was "Your call: re-scope ASK-148 or file (a) as a fresh issue".

The loop is pointed at a wall, and the wall is one Linear label wide.

## Was this solving the wrong problem?

Partly. The split is worth naming precisely.

**Right problem, correctly solved.** The review path: codex as reviewer, the
verdict record as single source of truth, `head_sha` pinning, the severity floor,
the silent-loss fixes, `engine`, `invoker`, and the fail-safe default of
`manual`. Nine rounds of codex finding real defects is not sunk cost. It is the
reason the record will be worth believing when it finally reads `worker`.

**Wrong problem, real time spent.** Treating the missing artifact as a wiring
defect. It stopped being one at 2026-07-30 17:37Z. Work after that point that
edited the review path was hardening a chain that was already complete. The
isolate-the-invoker branch is the cleanest example: careful, correct, and it
moves the artifact zero distance, because the runtime never reads `origin/main`.

**The named failure mode, recurring.** A green test standing in for the
behaviour. `test-review-invoker-provenance.sh` passes 7/7 and proves the field is
plumbed. It cannot prove a dispatcher ever set it, and never claimed to. The
distance between "the wiring is proven" and "the loop has done it" is the whole
remaining distance, and it is not closed by editing code.

## Recommendation

Discard nothing. Stop editing the review path. Give the dispatcher one issue that
yields a diff and let the existing machinery run.

Three ways, tradeoffs stated:

1. **Clear the wall, then use the test lane.** Take ASK-148 out of `ready()` the
   way Sana took ASK-149 out, then run
   `KIPI_DISPATCH_LANE=test bash kipi-dispatch.sh`. That lane exists at
   `kipi-dispatch.sh:278-289` with its own counter and a cap of 2, built for
   exactly this, and it spends no production slot. Fastest, and it exercises the
   real dispatcher rather than a stand-in.
2. **Wait for 07:00.** Costs nothing to build. Slot 1 burns on ASK-148 unless it
   is cleared first, and slots 2 and 3 are a coin flip on the same question.
3. **Teach the picker to prefer diff-yielding issues.** The durable fix, and the
   spillover ledger will want it eventually. It is also a new feature on a loop
   that cannot yet prove it works, so it belongs after the artifact, not before.

My call: #1. It is the only option that tests the thing that has never been
tested, and it requires trusting no new code.

## What I did not verify

- The outcome of 8 of the 14 dispatches (ASK-224 x4, ASK-225 x2, ASK-151, and
  ASK-223's first line). `kipi-dispatch.sh:364-374` documents the four ASK-224
  dispatches as launchd-reaped children that did no work. I read that as a claim,
  not a measurement, and did not confirm it.
- Whether ASK-148 is genuinely unexecutable. I read Sana's reasoning, not the
  issue itself.
- `attempts-ledger.py` line 44, deliberately and on instruction. Noting the shape
  only: the `break` at `:46` is reached only on a successful `os.mkdir`, so after
  100 failed tries the loop falls through and the mutation proceeds **unlocked**,
  which `:25-28` states as a deliberate trade. The release path then removes a
  lock directory it may not own. Real defect, out of scope for this judgment,
  and it wants a rested pass.

---

# CORRECTION, same day, after founder challenge

The founder rejected the recommendation on two grounds, both correct:

1. **Option 1 routed a Linear label edit to the founder.** That is implementation,
   and it violates the standing rule that Sana owns the work and the LOOP gets
   fixed rather than the founder doing a step by hand. Withdrawn.
2. **"What is an impossible job, and why is it even on the board?" was never
   answered programmatically.** It is answered below.

## Two predictions I made and got wrong

Stated before measuring, per the discipline this brief demanded.

| Prediction | Actual | Direction |
|---|---|---|
| 15+ of 29 ready issues are auto-filed | **29 of 29** | under-predicted |
| 3-6 of 29 are dispatchable | **13 of 29** | over-corrected |

Both errors point the same way: I was reasoning about the board instead of
querying it.

## What an "impossible job" is, defined in code that already exists

`linear-triage.py:326`:

```python
UNDISPATCHABLE_FLAGS = ("no-Files-line", "all-paths-outside-repo")
```

with `enforce_flags()` at `:329-355` deterministically overriding a `do-now`
triage verdict to `needs-scope` when either flag is set. Its own comment records
the measurement, made 2026-07-27: *"of 56 issues the worker considered READY, 13
carried no `**Files:**` line and 1 named only machine-local paths — 5 in 6 of its
own queue could never reach a terminal state."*

So the definition is not missing. It was written three days ago.

## The actual defect: the picker never reads it

`linear-worker.sh:230-236`, `ready()`, in full:

```python
def ready(i):
    labels = {l["name"] for l in i["labels"]["nodes"]}
    if "owner:assaf" in labels:      return False
    if "owner:sana" not in labels:   return False
    if i["state"]["type"] not in ("backlog", "unstarted"): return False
    d = i.get("description") or ""
    return "## Definition of Ready" in d or "Definition of Ready" in d
```

The last line is a substring match on a heading. It is the index standing in for
the thing: the presence of the words "Definition of Ready" stands in for "this
issue is executable". `enforce_flags()` is a producer with no consumer, which is
the inverse of this repo's own lesson
(`lessons/a-gate-is-only-real-if-production-writes-what-it-reads.md`) and a plain
`wiring-check.md` miss: an engine with no caller.

## Why the board is full of them

Measured against Linear just now, all 29 ready issues:

| Property | Count |
|---|---|
| ready | 29 |
| auto-filed by a detector (`<!-- kipi-key:`) | **29** |
| hand-written by a person | **0** |
| no `**Files:**` line at all | 13 |
| `**Files:**` naming no path that exists in this repo | 3 |
| naming at least one real in-repo path | 13 |

The producers are `fleet-health-daily.py` and `capability-map-gen.py`. They file
fleet-wide findings into one Linear team. The worker cuts every worktree from
`SKEL` (`linear-worker.sh:57`), which is kipi-system. Thirteen of the ready
issues are `Audit N unwired engines in <other repo>` — accountant, Alice,
KTLYST_strategy, investigations, gtm-partner and so on. The worker cannot check
those repos out. Nothing anywhere filters by target repo.

So the loop is a machine filing reports to itself, and a picker that cannot tell
a report from a task.

## Why the top pick is the worst pick

The pick is the first of the ready pool, which arrives descending by identifier,
so it is the highest-numbered ready issue: ASK-148. That is the one issue in the
dispatchable 13 that Sana has already refused, twice, on the correct grounds that
triaging 304 spillover items is not one bounded change. Its `**Files:**` line
names a real in-repo path (`prd_runner.py`), so a Files-based gate alone would
still pick it. The Files line is a second index: in-repo paths stand in for
bounded work.

## Why the existing self-clear is too slow to matter

`0d9700d` (today 16:27Z, local-only) bumps the attempt counter when a run opens no
PR. Three bumps mark an issue stuck. Verified: the ledger has no entry for either
ASK-148 or ASK-149 because all four no-PR runs predate that commit, so it has
never fired.

The arithmetic: 3 dispatches to retire one bad issue, 16 undispatchable issues,
3 dispatches per day. **~16 days of full budget to drain the board**, and its
terminal state is "stuck, needs a human", which routes to the founder — the thing
the founder just said must not happen.

## The loop fix, and it is Sana's

Two changes, both inside the loop, neither touching the founder:

1. **Wire `enforce_flags()` into `ready()`.** The classifier exists; give it its
   consumer. Drops 16 of 29 immediately and stops the queue handing Sana work
   that cannot yield a diff.
2. **One run, not three, and not to the founder.** Sana already writes a
   structured BLOCKED verdict. The worker should read it and apply a
   `needs-scope` label that `ready()` excludes and that routes the issue back to
   `linear-dor-drafter.py` for re-scoping. Today her only available move was
   relabelling ASK-149 to `owner:assaf`, which is the founder queue.

With both, the top pick becomes one of the twelve `CAP-NN` capability-manifest
issues, which are bounded, in-repo, and name real scripts. The receipt falls out
of the next dispatch without anyone touching Linear by hand.

## What is still unverified

- Whether the twelve `CAP-NN` issues are genuinely executable. They pass every
  mechanical test I ran; nobody has dispatched one.
- Whether `enforce_flags()`'s two flags are sufficient. ASK-148 passes both and is
  still unexecutable, so a third signal (bounded work) is probably needed and is
  not yet defined.

---

# CORRECTION 2, after founder asked "why can't Sana handle junk herself"

The question was the right one, and answering it invalidated the fix I proposed
in Correction 1. Three claims of mine were wrong.

## Wrong claim 1: "13 ready issues target other repos"

Measured properly, by Linear project rather than by reading titles:

```
11  kipi-system
18  everything else (ktlyst 4, 4_points 2, reddit-build-radar, negotiator,
    investigations, interview-coach, fractional-cxo, Pure_spectrum_Q,
    KTLYST_strategy, Alice, AUDHD_KIDS, ASK_AI_consultant, accountant, 1 unset)
```

**18 of 29, not 13.** The worker cuts every worktree from `SKEL`
(`linear-worker.sh:57`), which is kipi-system. Under two-thirds of its own ready
queue is for repos it cannot check out.

## Wrong claim 2: "wire enforce_flags() into ready()"

`linear-triage.py` writes its verdict as a **Linear comment**
(`comment_body()` at `:420-436`). Grepping the file for any label mutation
(`labelIds`, `issueUpdate`, `addLabel`) returns **0**. It has no launchd plist and
no caller anywhere in `kipi` or the scripts. It ran once, 2026-07-28, and died
mid-run after commenting on 74 issues.

So the classifier does not emit anything a machine can read. "Wire it into
`ready()`" was not a small change; it was an unwritten feature described as a
wiring fix. That is the same index-for-thing error this brief warns about: I saw
the right logic in a file and treated its existence as availability.

## Wrong claim 3 (overstated): "29 of 29 auto-filed"

What is proven: 29 of 29 carry a `<!-- kipi-key:` marker. Five scripts write that
marker, and one of them is `linear-dor-drafter.py`, which adds sections to issues
regardless of who created them. So the marker proves machine *touch*, not machine
*origin*. Two issues were confirmed detector-filed by reading them (ASK-148 says
"Filed by `fleet-health-daily.py`"; ASK-118 by `capability-map-gen.py`). The other
27 are unconfirmed. Downgrade the claim to: **the board is machine-maintained**.

## The answer to the founder's question

Sana has the judgment. She used it correctly on ASK-148 and ASK-149 and wrote
clear reasoning both times. What she lacks is any way to act on it.

The worker already contains a real loop over the whole ready pool:

```
linear-worker.sh:520   while IFS= read -r ISSUE; do
linear-worker.sh:1260    DONE=$((DONE+1))
```

It is disabled from outside. `converge.sh:151` invokes the worker as
`--apply --limit 1 --issue "$ISSUE"`, and the dispatcher hands converge exactly
one identifier. So by the time Sana is running, the board has already collapsed
to a single pre-chosen ticket. She can say yes or no to that ticket and nothing
else. There is no next ticket, and no way to mark the one she rejected.

That is the defect. Not a missing bouncer at the door: a chef with good judgment
and no menu.

## The revised fix

Give Sana the board instead of one ticket, and let rejection be a skip inside one
session rather than the end of a dispatch.

- **`--limit 1` becomes a budget, not a blindfold.** The worker loop already
  exists. Let a run read N ready issues, skip the ones Sana judges unexecutable,
  and spend its work on the first real one. Rejections then cost turns inside one
  session, not a whole dispatch each.
- **A rejection has to stick, and not land on the founder.** Sana's BLOCKED
  verdict needs a machine-readable outcome that `ready()` excludes. Today her only
  available move was relabelling ASK-149 to `owner:assaf`, which is the founder
  queue. A `needs-scope` label routing back to `linear-dor-drafter.py` closes it
  inside the loop.
- **Project scope is a one-line filter, and it is the cheapest win here.**
  `ready()` should exclude issues whose Linear project is not the repo the worker
  checks out. That is 18 of 29 gone for the cost of one predicate, and unlike the
  triage wiring it needs nothing that does not already exist.

The deterministic pre-filter I proposed in Correction 1 is not wrong in principle,
but it is the third priority, not the first, and the piece it depended on does not
exist yet.
