---
id: bookkeeping-must-never-gate-the-deliverable
kind: pattern
title: Bookkeeping must never gate the deliverable
date: 2026-08-10
---

When one run both produces a deliverable and writes per-item bookkeeping (receipts, status marks, sync rows), four things decide whether a single transient error costs you one row or the whole run.

**1. Rank the outputs before you write the code.**
Name which output is the reason the run exists, and which outputs are internal bookkeeping. The deliverable goes out first, or the bookkeeping gets wrapped so its failure cannot propagate past it. Any refactor that moves bookkeeping earlier in the call path is a change to delivery availability, not a neutral reorganization. Review it as such.

**2. Independent items get independent failure domains.**
If each write is a standalone fact about a separate item, a single loop with one shared failure path converts one network blip into total loss of every remaining item. Catch per item, continue, accumulate failures, and report partial success at the end with the failed items named.
The test: does item N's failure logically say anything about item N+1? If no, isolate them.

**3. Data your code did not produce is an unverified contract until you have read a real instance.**
A shape you assumed for another system's output is a guess, even if every function around it is correct and tested. Before coding against it, capture one real sample from the producer and pin the parser to it. If the producer's runtime is unreachable, make the reader defensive at the boundary: validate the shape on arrival, and fail loudly with the observed shape rather than silently on the assumed one.

**4. A fixture written from the same mental model as the code cannot falsify that model.**
A suite that is green on invented inputs is self-consistent fiction, and its size is not evidence. For every external boundary, at least one fixture comes from a captured real producer run, and at least one check reads live state instead of a fixture.

**Applying it:**
- List the run's outputs, mark exactly one as the deliverable.
- Wrap each per-item side effect in its own try/continue, collect errors, summarize at the end.
- For each input the code did not produce, point at the captured real sample that justifies the parsing logic. If there is none, that is the first gap to close.
- Before shipping, ask: which failure could take out the deliverable, and is that failure in the deliverable's own path or in bookkeeping?
