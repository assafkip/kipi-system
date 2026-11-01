---
id: pin-shared-identifiers-to-one-source-across-process-boundari
kind: pattern
title: Pin Shared Identifiers to One Source Across Process Boundaries
date: 2026-11-01
---

When two separate processes must agree on a single logical value (a correlation id, run id, trace key, tenant key, or similar), treat that value as a contract artifact rather than something each side derives on its own.

How to do it:

1. Declare one authoritative source. Pick exactly one channel for the shared value (for example: the payload passed between the processes, or an explicitly documented environment variable) and write it down next to the code that reads it. If both channels must exist for compatibility, declare one as primary and the other as a fallback that logs a warning when used.

2. Centralize the read. Put the resolution logic in a single shared helper that both the producing and consuming side call. Never let each side independently decide where the value comes from; two independent derivations are two independent guesses that silently diverge.

3. Verify the channel against the real runtime, not against assumptions. If the value arrives via ambient configuration supplied by an external runner or harness, dump the actual ambient state once from inside the running process and confirm the exact name and format. Names assumed from documentation, memory, or analogy are a common silent failure: the read succeeds, returns empty or a default, and the system keeps running while producing nothing useful.

4. Fail loudly on absence. Make the resolver raise, or emit a clearly tagged error record, when the shared value is missing or malformed. Avoid defaulting to an empty string, a fresh random value, or a placeholder, because each of those turns a wiring bug into data that looks plausible but never joins.

5. Add a cross-boundary test that pins the handshake. Write a test that exercises producer and consumer together and asserts the value observed by the consumer equals the value emitted by the producer. Unit tests on each side in isolation will both pass while the join is broken, so the assertion must span the boundary. Where a real two-process test is impractical, assert that both sides invoke the same resolver and that the resolver has a single code path.

6. Add an end-to-end liveness check for the join itself. For any pipeline whose whole purpose is to associate records across a boundary, monitor the count of successfully joined records, not just the count of records written on each side. A boundary that records zero joins while both halves report success is the signature of this class of bug.

General principle: any value that must be identical on both sides of a process boundary needs one source, one reader, one test that compares the two observations, and a hard failure when it is absent. Symmetric-looking code on each side is not evidence of agreement.
