---
id: checkpointing-long-mechanical-refactors
kind: methodology
title: Checkpointing Long Mechanical Refactors
date: 2026-10-31
---

## When to use

Any bulk, mechanical change that spans more sites than one work session can finish: a rename across a codebase, a dependency or API migration, a lint-rule rollout, a config-key sweep. These jobs fail in a characteristic way — several runs start over from scratch, each rediscovering the same inventory, and the final diff touches things nobody asked to touch.

## Core rule: nothing durable, nothing done

Treat any progress that exists only in a process's memory or in an uncommitted working tree as already lost. A session can be stopped, time out, or be torn down by its parent at any point. Design the work so that every unit of progress lands on disk in a form a fresh session can pick up.

### How

1. **Write the inventory to a file first.** Before changing anything, enumerate every site that needs to change and commit that list as a checklist artifact. Enumeration is usually the expensive, intelligent part of the job; the edits are cheap. Losing the list means paying the expensive part again. A list recited in prose inside a session is not an artifact.
2. **Commit per batch, not per job.** Replace "finish everything, run the full suite, then commit" with "complete one batch, run the narrow checks that cover it, commit, tick the checklist." Partial work on a branch is recoverable; partial work in a dirty tree is indistinguishable from noise.
3. **Record the stopping point explicitly.** At the end of each batch, append to the artifact: what is done, what is next, and any site deliberately skipped plus the reason. Resume reads this file, not the transcript.
4. **Make the artifact the source of truth for "remaining."** Deriving "what's left" by re-scanning the code each run invites drift, because the scan's results depend on how far the rename already got.

## Core rule: don't detect progress by one signal

A supervising session that checks "has prior work happened?" by counting commits will report zero and declare a clean start, discarding real edits sitting in the working tree. In an environment where the tree is routinely dirty from unrelated churn, "uncommitted changes" is not evidence of nothing, and absence of commits is not evidence of nothing.

### How

- Check for the handoff artifact first, then commits, then the diff. Only conclude "clean start" when all three are empty.
- Separate intentional work from ambient churn by convention — a dedicated branch, a scoped directory, a named artifact — so a later reader can tell them apart without judgment calls.
- Before overwriting or restarting, state out loud which signal was consulted and what it showed. This forces the weak inference into the open.

## Core rule: validate a negative search before trusting it

Concluding "this never happened" from a zero count is only sound if the counter works on these inputs. Run the same query for a term you know is present. If the control also returns zero, the query or the input format is wrong, not the history. Apply this to log greps, audit scans, metric queries, and test-selection filters alike — anywhere a zero is about to become a conclusion.

## Core rule: a rename changes names, not values

Mechanical sweeps drift into semantic changes when the executor has latitude. Guard the boundary:

1. Write down, before starting, the exact transformation: which token becomes which token, and that nothing else changes. Anything outside that is a separate task with its own approval.
2. Prefer a scripted or tool-driven transformation over hand edits for the repetitive core, so the diff is uniform and reviewable by shape.
3. Review the final diff for lines that are neither old-name nor new-name. Each one needs a stated reason or gets reverted.
4. If a site genuinely cannot be renamed without a semantic change, stop and log it on the checklist as blocked rather than improvising a fix mid-sweep.

## Core rule: triage failure counts, don't chase them

When a bulk change produces a large failure count, resist iterating on the number. Group failures by cause, pick the group with the highest count, and confirm that one site or one pattern explains it. Large counts in mechanical sweeps almost always trace to a small number of hub sites — a registry, a dispatch table, a shared fixture — where the old name is constructed or looked up dynamically rather than written literally. Fix the hub, re-measure, then re-group. Treating the count itself as the work product produces fix cycles that each move the number without resolving a cause.

## Pre-flight checklist

- Is the inventory committed as a file?
- Does a resume path exist that reads only on-disk state?
- Is the batch size small enough to commit inside one session?
- Is the allowed transformation written down narrowly?
- Do the progress checks consult more than one signal?
- Has every zero-result query been validated with a known-positive control?
