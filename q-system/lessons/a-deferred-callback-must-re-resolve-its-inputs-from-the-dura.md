---
id: a-deferred-callback-must-re-resolve-its-inputs-from-the-dura
kind: pattern
title: A deferred callback must re-resolve its inputs from the durable contract, not close over an earlier stage's scope
date: 2026-07-06
---

When you register a callback, gate, or hook that fires in a LATER stage than where it was defined, it will outlive the local scope it was written in. Any value it reads that was only a local variable at definition time is a landmine: by the time the callback runs, that scope may be gone, rebuilt, or never entered on the real path, and the reference resolves to nothing.

HOW to build it safely:

1. Identify the STABLE source of every value the callback needs. If your system has a registry, store, or shared context that is the durable owner of that data, the callback re-resolves from it AT CALL TIME. It does not capture a copy from the surrounding stage.

2. Draw the line between 'defined here' and 'runs there.' For each variable the callback touches, ask: does this exist in the callback's own runtime scope, or am I borrowing it from the enclosing function that has already returned? Borrowed values get replaced by a lookup against the durable source.

3. Treat the callback's inputs as a contract, not a closure. Pass an explicit handle to the durable source (or the key needed to query it) instead of relying on lexical capture. Explicit-and-queried beats implicit-and-captured every time the two stages are separated in time.

HOW to test it so the gap can't reach production:

4. Component tests over the callback's behavior in isolation are necessary but NOT sufficient. They exercise a scope you constructed for the test, which is exactly the scope that does not exist on the real path.

5. Add one test that drives the ACTUAL wiring: build the callback the same way the real entry point builds it, with the real construction arguments, and invoke it through the path production uses. This is the test that surfaces an undefined-reference or missing-lookup bug, because it reproduces the real scope, not a convenient one.

6. Rule of thumb: if a defect could live in the SEAM between two stages (definition-time vs. call-time), a test that only touches one stage will never catch it. Test the seam.
