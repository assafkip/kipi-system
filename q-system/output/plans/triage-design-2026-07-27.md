# Triage: what deserves a run — problem 5, Sana's call

Written 2026-07-27 22:15Z. Measured against the live board, not the brief.

## The brief's premise does not survive the data

The build brief says:

> Roughly 44 of those were filed automatically by scanners (`fleet-health`,
> `launchd-health`) — inflow is automated, outflow is manual, so the board only
> grows.

Measured across all 208 open ASK issues, of the 56 that pass the readiness filter:

```
32  job-migration     one per launchd job
14  Audit <instance>  one per fleet instance
 3  fleet-health
 3  kipi-system       the loop's own work
 3  ktlyst
 1  hand-filed
```

`fleet-health` filed **3**, not 44. The 32 migrations are not junk: 26 `com.cole.*`
jobs are paused *pending exactly this migration*, on the founder's instruction. The
14 audits are a deliberate fleet fan-out. **Volume here is intent, not noise.**

Closing them as scanner spam would have deleted the founder's own backlog. This is
why triage is a decision made against the board, not against a heuristic.

## The real disqualifier: can the loop even work this issue?

The worker's flow is worktree → commit → PR → review → merge. An issue whose
deliverable is not a diff in **this** repo produces no PR, so `converge.sh` exits 7
(*"no PR after round 1"*) and burns an attempt. That is a structural mismatch, not a
preference. Measured on the `**Files:**` line of all 56:

| bucket | count | dispatchable? |
|---|---|---|
| in-repo paths only | **9** | yes |
| mixed repo + machine-local (`~/Library/LaunchAgents`, `/Users/...`) | 33 | only if the repo half is real work |
| **no `**Files:**` line at all** | **13** | **no** |
| machine-local only | 1 | no |

So the honest dispatchable count today is **9**, not 55. The loop has been picking
from a pool where 5 in 6 issues cannot reach its terminal state.

The 13 with no `**Files:**` line are the same set problem 4 flags: *"issues with no
declared files are exactly the ones that should not auto-dispatch."* One check
serves both — file-disjointness and dispatchability read the same field.

## The triage gate: four buckets, recorded on the issue

Runs before dispatch, never as a side effect of it. Every decision writes a Linear
comment naming the rule that fired, so the reasoning survives and is reversible.

| bucket | rule | what happens |
|---|---|---|
| **dispatch** | has a `**Files:**` line, ≥1 path inside the repo, disjoint from every in-flight issue | enters the queue |
| **needs-scope** | no `**Files:**` line, or every path is machine-local | comment naming the missing field; label `needs:scope`; drops out of ready. Not closed |
| **batch** | ≥5 ready issues share a `kipi-key` producer prefix and one DoR shape | one tracking issue; the group is not dispatched individually |
| **park** | superseded, duplicate, or its target no longer exists | comment with the reason and a link; closed. Reversible by reopening |

Nothing is deleted. `needs:scope` is the honest state for most of the board: the
issue is real, the DoR is not yet machine-actionable.

## Why `batch` exists, and why it is the highest-value bucket

The 32 migrations share one DoR shape (verified: normalise job name, path and
number out of each description and they collapse to one template). Dispatching 32
converge loops means 32 × ~20 min × model spend to make 32 near-identical plist
edits, each with its own review round.

**That is the wrong shape.** A repetitive change across N targets is one script plus
N config entries, reviewed once. The batch rule turns a 32-issue queue into a
1-issue queue and a table.

Threshold is 5 rather than 2 so genuinely-independent siblings still run
individually. The rule reads the `kipi-key` prefix that the filing scanners already
write, so it needs no new metadata.

## A scanner's volume is a fact about the scanner

The brief's line — *"volume from one detector is a signal about the detector"* —
holds, and the triage step is where it gets recorded. When a producer prefix crosses
the batch threshold, the tracking issue carries the count. Three consecutive batches
from the same detector is a finding about the detector, captured as spillover, not a
reason to close its output.

## Build shape

`q-system/.q-system/scripts/linear-triage.py`, dry by default like every other
script here.

- Reads the same ready-filter `linear-worker.sh` uses. **Shares it, never
  reimplements it** — two readers of one filter with drifting semantics is the
  defect class this repo keeps killing.
- `--apply` writes labels and comments. Prints the bucket table either way.
- The worker's ready-filter gains one clause: `needs:scope` is not ready. That is
  the deterministic half; the bucketing rules above are the rest.

**Verification:** run it dry against the live board and assert the counts in this
document (9 / 33 / 13 / 1). Those numbers are the reproducer.

## What I am NOT doing

- Not closing the 32 migrations. They are the founder's paused jobs.
- Not closing the 14 audits.
- Not building a priority score. Dispatchability is objective; "worth doing" is not,
  and a fake score would launder a guess into a number.
