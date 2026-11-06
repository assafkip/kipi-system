---
id: validating-automated-guardrails-before-they-ship
kind: methodology
title: Validating Automated Guardrails Before They Ship
date: 2026-10-31
---

## When to apply

Any time you add an automated enforcement layer — a pre-action hook, a commit gate, a policy check, a lint rule that blocks, a CI guard — that interposes on the same operations an approved workflow must perform. These layers can deadlock: the rule forbids the very actions required to reach the state that satisfies the rule.

## How: separate categories by intent, not by surface form

1. Before writing any matcher, list the acts the guard must **block** and the acts the workflow must **perform**. Write them as two explicit sets.
2. Compare the sets. If any act appears in both, stop — you have a category error, not a tuning problem. No refinement of the pattern will fix it.
3. Resolve by splitting the category along intent rather than along the shape of the invocation. Two operations can look identical on the wire (same binary, same verb) and still be opposites: one is the output the guard exists to withhold, the other is the measurement that earns the right to produce it.
4. Name the matcher after the forbidden intent, not after a loose family of verbs. A name that groups three unrelated verbs under one of them is a sign the set is a superset of what you meant.
5. Give the required acts a distinguishing marker the guard can read — a dedicated entry point, an explicit flag, an environment signal, a scoped target — so the guard can permit the enabling act while still blocking the forbidden one.

## How: test the transition, not the end state

6. Audit existing tests for hand-constructed state. A test that writes the artifacts a workflow is supposed to produce, then asserts the guard accepts them, proves only that a *finished* workflow unblocks. It never proves a workflow can *be* finished.
7. For every guarded workflow, add at least one test that drives the real steps in order and lets each step produce its own artifacts. The defect you fear lives in the interval between "work done" and "evidence exists" — exactly the interval a fixture skips.
8. Exercise the guard through its real interception point. Invoking the underlying tool directly, as a subprocess or library call, bypasses the hook and tests nothing about the hook.
9. Treat these as distinct assertions and keep both: *the accepting end state is accepted*, and *the path to that end state is traversable*. Passing the first while failing the second is the characteristic failure.

## How: run the thing once, in a real session

10. Never land the guard, its configuration, its checker, and the workflow it governs in a single change that was only reviewed as files. Reading cannot detect absence; only execution can.
11. Make one end-to-end manual run against a real instance a required step before merge. Capture the transcript as the artifact of record.
12. If end-to-end execution is impractical, land the guard in observe-only mode first — log what it *would* have blocked — and promote it to blocking only after the logs show it never fires on legitimate workflow steps.
13. Prefer staging the guard after the workflow it enforces has been exercised in production at least once, so the permitted path is known-good before anything starts refusing traffic.

## Checks before merge

- The blocked set and the required set are written down and provably disjoint.
- At least one test traverses the full workflow through the guard's real interception point, with no hand-written artifacts.
- A human has executed the governed workflow start to finish in a live session, and the transcript is attached.
- Every matcher name describes exactly one intent.
