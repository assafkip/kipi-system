---
id: serialize-the-whole-read-modify-persist-section-not-just-the
kind: pattern
title: Serialize the whole read-modify-persist section, not just the final write
date: 2026-07-06
---

When a shared resource is guarded by a single-writer or mutual-exclusion primitive, check where that guarantee actually starts and ends. A common failure: the low-level write is serialized, but the read-modify-encode-commit sequence around it is not. If two operations each snapshot the current state, transform it, and then commit asynchronously, the operation that commits last wins — and it may be carrying an older snapshot, silently erasing the other's change. This is a classic lost update, and it hides because each individual write looks correct.

The trigger is often subtle: a resource that only ever had one writer gains a second, un-awaited one as a side effect of some unrelated action. The new writer runs concurrently with the original path, and the two overlap inside a critical section nobody thought was contended.

HOW to hold the line:
- Define the critical section as the full span from reading the current state to durably committing the new state, not just the moment of the write call. The invariant you need is: no two of these spans interleave.
- Route every mutation through one serialization point (a queue, a lock, or an awaited single-writer channel) that covers that whole span. Awaiting the low-level write alone does not serialize the snapshot-then-transform step that precedes it.
- Treat any new un-awaited, fire-and-forget writer to a shared resource as a contention change. Ask what else can be writing at the same time before adding it.
- When you add a second writer to something that historically had one, re-derive the concurrency assumptions of the existing writer; they were likely written assuming exclusivity.

Separately, when you build a test that asserts an outcome through a proxy signal, verify the proxy is uniquely tied to that outcome by construction, not by accident. A proxy that happens to be unique only because of an unstated assumption ("this event never repeats") becomes a false pass the moment a legitimate new behavior violates that assumption. Assert on the durable artifact you care about, and if you must use a proxy, encode what makes it unique so a future behavior change breaks the test loudly instead of passing silently.
