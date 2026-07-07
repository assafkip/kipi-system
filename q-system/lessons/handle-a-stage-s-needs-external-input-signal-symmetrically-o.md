---
id: handle-a-stage-s-needs-external-input-signal-symmetrically-o
kind: pattern
title: Handle a stage's "needs-external-input" signal symmetrically, or it becomes a silent hard-halt
date: 2026-07-06
---

When a multi-stage pipeline lets any stage emit a "needs more input" signal (a clarification request, a missing-field prompt, an ambiguity flag), two failure modes hide in it. First: the signal assumes an input channel that may not exist for every deployment. A stage designed around a human who answers becomes a dead end the moment it runs in a context where nobody can answer — the pipeline halts with an empty result and no error, because from the code's view everything went 'fine, awaiting reply.'

How to build it safely:

1. For every stage that can request input, decide its behavior when NO answer will ever arrive. Give it a bounded fallback: cap the number of clarification rounds, then auto-inject a default response and continue, or emit a degraded-but-nonempty result. 'Wait forever' is not a behavior; it is an omission.

2. Make the handling of one signal class identical across stages. If stage A treats an unanswerable request as fatal while stage B degrades gracefully, that asymmetry IS the bug — the same class of event should not be recoverable in one place and terminal in another. Audit each stage against the others for the same signal type.

3. Treat a stage that yields zero output through a 'clean' path as an alarm, not a success. A run that completes with an empty result and no error is the signature of a silently unanswerable prompt. Add a check that distinguishes 'finished with real output' from 'finished because it gave up waiting.'

4. Watch for environments that MASK the defect. When two runtime paths handle the same step differently (a privileged/local path versus a plain path), the developer's environment can silently exercise the forgiving path while every other deployment hits the strict one. 'I can't reproduce it' plus 'it always fails for them' is the tell: reproduce on the same path the failing environment uses, not the one your machine defaults to. Removing or disabling the privileged path exposes the latent defect that was always there.

The durable rule: an input-requesting step must define its no-answer behavior, that behavior must match its sibling steps, and an empty clean exit must trip an alarm rather than pass as done.
