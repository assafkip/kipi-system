---
id: when-a-view-can-be-torn-down-mid-run-one-chokepoint-must-own
kind: pattern
title: When a view can be torn down mid-run, one chokepoint must own the run's fate
date: 2026-07-20
---

A long-running job that renders into a view creates a lifecycle question the moment the view can be destroyed while the job is still going: what happens to the run when its view goes away? If no single place owns that answer, the default answer is "nothing" — the run orphans and any in-flight state it produced is lost. Three failure modes tend to co-occur.

1) Lifecycle decoupled in the wrong direction. Cancellation/abort is wired to the obvious triggers (an explicit stop control, a context switch, a superseding run) but not to view teardown itself (navigation, re-render, unmount). So teardown destroys the view without aborting, pausing, or checkpointing the run. Fix: route every teardown path through the same abort/handoff chokepoint the explicit controls use. Make teardown-during-run a decision that is written down in one function, not an emergent gap.

2) In-flight growth lives only in the ephemeral view. When a run mutates a live, view-owned object incrementally and only persists to the durable model at finalization, the live view becomes the sole home for in-flight state. Tear the view down before finalization and a rebuild rehydrates from the last persisted snapshot — which predates the in-flight work — so the state visibly reverts. Fix: persist incrementally as the run produces state, or checkpoint on teardown, so the durable model is never behind the live view by more than one step.

3) No test exercises teardown-during-run, so the class recurs. Happy-path tests drive a run to completion without ever navigating away mid-run, leaving the interesting concurrency uncovered. Each new symptom (a stale callback firing into a destroyed view, an orphaned timer, a reverted display) looks like a fresh bug but is the same missing invariant. Fix: add a test that asserts "a teardown during an active run either aborts cleanly or preserves the run" — and treat the Nth recurrence of this shape as evidence the invariant is missing, not as N unrelated bugs.

General rule: any resource whose lifetime can outlive the view it renders into needs one owner for the teardown-during-life question, incremental persistence so no durable state trails the live copy, and a test that drives teardown mid-life.
