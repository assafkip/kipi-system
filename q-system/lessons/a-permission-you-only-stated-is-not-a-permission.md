---
id: a-permission-you-only-stated-is-not-a-permission
kind: pattern
title: A permission you only stated is not a permission
date: 2026-08-24
---

Two failure shapes show up together whenever an automated actor is given a scoped job in a shared workspace.

**Shape 1: the remit lives in the prompt, not the capability set.**
A worker is told "only report, do not change anything." The instruction is the sole constraint; the worker still holds every write and spawn capability the platform grants. Nothing blocks the disallowed action, so the first time the worker interprets its job loosely, it acts. If the intended remit is read-only, hand it a read-only capability profile. If the intended remit is one directory, mount one directory. A capability boundary makes the violation impossible; a sentence only makes it discouraged.

**Shape 2: shared mutable state with no owner token.**
A single global slot (an active-task record, a lock file, a current-context pointer) accepts a transition from any process that can reach it. "Only the actor that opened this may close it" is an assumption living in nobody's code. When concurrency is a supported mode of the system, this is a latent defect, not bad luck. Fix: stamp the record with an owner identity at open time, and have every transition verify the caller matches before it writes. Reject with a clear error instead of silently completing someone else's work.

**The diagnostic trap that follows.**
When a state record looks corrupt, verify the decoder before you accuse the data. Reading a record with guessed field names prints empty values for every field, and empty reads as missing. A first postmortem can then report a data-integrity gap that does not exist, sending fixes at the wrong layer. Before concluding a record is malformed, print the raw line and compare it against the writer's actual schema. Retract the wrong diagnosis explicitly when the raw evidence contradicts it; a quietly abandoned root cause leaves the real one unfixed.

**Checklist**
- For each automated actor: list what it can do, not what it was told to do. Narrow the grant to the job.
- For each shared state slot: name the owner field. If there is none, concurrent writers can trample each other.
- For each transition on that slot: confirm the caller's identity matches the recorded owner.
- Before diagnosing corruption: dump the raw record and match field names against the writer.
