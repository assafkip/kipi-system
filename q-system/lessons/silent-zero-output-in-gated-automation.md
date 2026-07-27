---
id: silent-zero-output-in-gated-automation
kind: pattern
title: Silent zero-output in gated automation
date: 2026-07-27
---

An automated delivery lane that publishes nothing looks identical to one that had nothing to publish. Both read as a quiet, healthy run. Design so the two can never be confused.

## 1. Never gate an automated action on a sampled judge with no determinism control

If the gate calls a model through an interface that exposes no temperature or seed, the verdict is resampled per call. Identical clean input can pass or hold at random. Fail-closed is the right default for safety, but fail-closed plus non-deterministic means good output is silently withheld on an unlucky roll, and the symptom presents as a content problem rather than a gate problem.

How:
- Pin sampling parameters when the interface exposes them.
- When it does not: vote across repeated calls, and cache the verdict keyed by a hash of the exact input so a rerun cannot flip it.
- Persist the verdict plus its stated reason alongside the artifact, so the next debugging pass starts at the gate rather than at the content.
- Reserve hard blocking for deterministic checks. A judged, non-reproducible check earns a hold-with-alert, not a silent drop.

## 2. Make an unregistered caller fail loud, not inherit the strictest default

Policy keyed by lane name with a silent fallback entry means any caller added later quietly inherits rules authored for a different kind of work. The mechanism exists and looks correct; the new lane was simply never wired into it.

How:
- Resolution of an unknown key raises, it does not fall back.
- A test enumerates every call site's key and asserts each maps to an explicit registered entry.
- Registration is a line item in the checklist for adding a lane, not tribal knowledge.

## 3. Every runner asserts its own environment

Sibling runners drift: one sources the credential file, the other never did. The gap stays invisible while the failing dependency is the second write.

How:
- Assert required variables at process start; exit non-zero with the missing names.
- Environment loading lives in one shared preamble that runners source, not copy-pasted per script.

## 4. A failed remote write must not be masked by a successful local write

When a step writes both a local record and a remote ledger, a credential failure on the remote path still leaves the local write green. The run reports success and the two stores diverge silently.

How: the authoritative store decides success. The local copy is a cache. Propagate the remote error, mark the record unsynced, and reconcile on the next run.

## 5. Alarm on zero

Any lane expected to act on a schedule emits a count every run, and a count of zero pages exactly like a crash does. Emit a reason code with it: gate held, no candidates, auth failure, upstream empty. "Withheld" and "nothing to do" are different states and must never share a log line.

## Diagnostic order when a scheduled lane delivers zero

1. Did the job run at all?
2. Did it produce candidates?
3. What did the gate decide, and is that decision reproducible on the same input?
4. Did every write succeed, or only the first one in the chain?
