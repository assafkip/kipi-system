---
id: protect-loop-input-streams-and-assert-iteration-completeness
kind: pattern
title: Protect Loop Input Streams and Assert Iteration Completeness
date: 2026-10-31
---

When a shell loop reads a list of work items and runs commands for each one, two independent failure modes can silently truncate the sweep. Guard against both.

**1. Keep the loop's input stream out of reach of child commands.**

A `while read` loop driven by a redirect or process substitution attaches that stream to the loop body's standard input. Any command inside the body that reads standard input — intentionally or not — consumes the remaining items from the loop's own feed. The loop then exits early with no error, no non-zero status, and no log line indicating anything was skipped. The failure is data-dependent: it only triggers when a particular item causes a child to read stdin, so it can hide for a long time and then appear intermittently.

Use one of these patterns, and prefer them unconditionally rather than only where you think a child reads stdin:

- Redirect each child command's stdin from the null device.
- Read the loop on a dedicated file descriptor and attach the feed to that descriptor, leaving fd 0 free for children.
- Materialize the list into an array or variable first, then iterate over it in memory so no stream is shared at all.

The same hazard applies to any language or tool where a subprocess inherits the parent's stdin while the parent is mid-read on it. Treat an inherited readable stream as a shared, drainable resource: if you are iterating over it, no child may touch it.

**2. Give every sweep a per-run completion invariant.**

"The loop exited without error" is not evidence that the loop visited every item. Make completeness explicit and checkable:

- Count the input items before the loop starts and record that count.
- Increment a counter inside the loop body, once per item actually processed.
- After the loop, compare the two and fail loudly if they differ, naming the shortfall.
- Emit one structured log record per item so a reader can reconstruct which items were visited and diff that against the input list.

This turns a silent truncation into an immediate, attributable error at the point of failure instead of a downstream symptom.

**3. Test the condition that actually breaks it.**

A test that exercises a list where every item behaves uniformly will pass even with the stdin bug present. Write a test where an item in the *middle* of the list triggers the hazardous behavior — a child that reads stdin, spawns a subprocess, or otherwise touches the shared stream — then assert that items *after* it were still processed. Assert on the per-item record count, not merely on exit status.

**4. Treat an after-the-fact auditor as a backstop, not a substitute.**

A separate reconciliation job that compares expected versus observed state will catch the symptom and is worth having. But it reports late, often on a fixed schedule, and it describes the effect rather than the cause. It does not remove the need for an in-loop invariant: the invariant localizes the defect, and the auditor only tells you that something, somewhere, drifted.

**Checklist for any fleet-wide or registry-wide sweep:**

- Does any command in the loop body inherit the loop's input stream? Isolate it.
- Does the run assert items-in equals items-processed? Add it.
- Is there a per-item log record enabling reconstruction of coverage? Add it.
- Does a test place the hazardous item mid-list and assert the tail still ran? Add it.
- Does a partial sweep exit non-zero and alert, rather than looking like a clean run? Make it so.

The general principle: a loop that can end early without signaling is worse than one that crashes. Make partial completion a loud, first-class error, and never let the thing being iterated over be reachable by the things doing the work.
