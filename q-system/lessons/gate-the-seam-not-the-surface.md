---
id: gate-the-seam-not-the-surface
kind: methodology
title: Gate the seam, not the surface
date: 2026-07-06
---

A feature that passes on its own surface is not done; done is the seam to the next surface being connected and provable. When two surfaces must join, the join is the deliverable, not an afterthought. Three failure modes all reduce to one cause: connection is left to author discipline instead of a deterministic gate.

HOW:

1. Redefine done as connected, not local. A surface passing in isolation (its view renders, its control exists, its own acceptance is green) is a precondition, not completion. Write acceptance criteria that name the seam: input arrives from the upstream surface AND output is consumed by the downstream one. If nothing fails a build when an end dangles, the connect step is the one that gets dropped under pressure.

2. Make the seam-check deterministic, not advisory. A rule that says 'verify end-to-end at task end' runs at the author's discretion and gets skipped exactly when time is short. Convert it into something that fails the build: a check that every producer has a consumer and every consumer a producer, run automatically, blocking on red. Author intent does not hold a seam; a gate does.

3. Distrust the forgiving environment. When you build and test inside an environment that supplies capabilities for free (navigation, state, refresh, back, multi-view), you may never build those capabilities yourself; the environment masks their absence. 'Works in my dev environment' is a masking condition, not a done bar. Before shipping, exercise the feature in the target environment that does not supply those freebies. The latent defect surfaces the instant the mask is removed.

4. Convert deferrals into tracked work at the moment they are written, not later. 'Open for later / follow-up / deferred / open question' living as prose evaporates the moment the containing document is closed or archived. Any deferral must become a tracked item the same instant it is stated, through the same mechanism that tracks primary work. A deferral that is not in the tracker is a silent drop.

The through-line: if a connection, a capability, or a follow-up depends on someone remembering to do it, it will be dropped. Wire each into a check that fails when it is missing.
