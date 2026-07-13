---
id: make-cold-load-reconstruction-share-a-contract-with-the-live
kind: pattern
title: Make cold-load reconstruction share a contract with the live view, and treat the Nth recurrence as a missing invariant
date: 2026-07-13
---

When a UI builds state two ways — incrementally from a live stream during a session, and by reconstruction from a durable store on reload — the two paths will drift unless something forces them to agree. The failure shape: the live view populates correctly while work happens, but the promotion step that writes results into the durable record silently produces zero rows, so a reload (which reads only the durable store) shows an empty state while sibling features that persist eagerly restore fine.

How to prevent and fix it:

1. Define the invariant explicitly: anything the live view displays must be recoverable from the durable store alone. Write it down as a contract between the stream consumer and the reload path.
2. Enforce it with a reload-equivalence test: run a session that produces state through the live path, simulate a cold load, and assert the reconstructed state matches what the live session displayed. Assert on counts and content, not just on absence of errors — a run that reports success with zero promoted records is the exact case this test exists to catch.
3. Collapse to a single writer where possible: have the live view render FROM the durable record (write-through, then read) instead of maintaining a parallel in-memory copy that someone must remember to flush. If a parallel copy is unavoidable, make the flush unconditional on every terminal state (success, abort, budget-exhausted), not only on the happy path.
4. Treat recurrence as a diagnostic signal: when the same symptom class returns after multiple fixes, each prior fix patched one producer path. Stop patching instances. Enumerate every code path that can produce the state, find the invariant none of them individually owns, and move enforcement to a shared chokepoint (one write function, one schema check, one test) that all paths must pass through.
5. When diagnosing, inspect the actual stored records for the failing case (shapes and counts) rather than reasoning from the code — the discrepancy between 'many successful steps' and 'zero promoted results' is visible in the data long before it is visible in the logic.
