---
id: unowned-data-contracts-and-per-item-write-loops
kind: pattern
title: Unowned data contracts and per-item write loops
date: 2026-08-03
---

When your code consumes a file, payload, or record produced by a runtime you do not own (another team's job, a hosted agent, a third-party callback), the shape you coded against is a guess until a real sample proves it. Fixtures you author yourself cannot falsify that guess: they encode the same mental model as the code, so the suite goes green on a fiction. Before shipping logic that parses external output, capture one real artifact from the producing runtime and pin at least one test to that captured sample. If the producer's filesystem or runtime is unreachable, add a step that makes it echo its output somewhere you can read, and treat the parser as unverified until that lands.

Second rule, independent of the first: when you write N independent records in a loop, isolate each iteration. A record about item three says nothing about item four, so one transient network failure should cost one record, not the tail of the batch. Wrap each write in its own error boundary, collect failures, continue, and report the partial result with the list of what did not land. Retry only the failed subset.

Third rule: rank the deliverable above the bookkeeping. If a routine both produces the artifact a human consumes and records internal state about that production, the state write must never sit on the path that can abort the delivery. Emit the deliverable first, or wrap the bookkeeping so its failure degrades to a warning attached to the delivered output. Watch for this specifically when refactoring: moving a write into an earlier function for convenience can silently place internal accounting in front of the only thing anyone reads.

Application checklist: (1) name every input your repo does not produce and mark each as unverified until a captured live sample exists; (2) for any loop of independent writes, verify a mid-loop exception cannot skip later items, and add a test that injects a failure at one index and asserts the others still wrote; (3) trace the code path from entry to the user-visible output and confirm no internal state write can throw before it; (4) treat a fully self-authored fixture set as zero evidence about an external contract, and say so in the test file so the next reader does not mistake green for verified.
