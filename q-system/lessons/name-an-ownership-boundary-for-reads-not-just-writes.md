---
id: name-an-ownership-boundary-for-reads-not-just-writes
kind: pattern
title: Name an ownership boundary for reads, not just writes
date: 2026-07-27
---

When one module owns a shared resource (a file, a table, a queue, a cache key), the boundary that matters is who may NAME it, not who may WRITE it. A read that bypasses the owner API is still a bypass: it duplicates the location, the format assumptions, and the load semantics, then drifts silently the moment the owner changes any of them. An invariant called "single writer" actively invites a read-only caller to assume it is exempt.

How to apply:

1. Name the invariant after what it forbids, not after the common case. "Single writer" is ambiguous at the edge. "All access routes through the owner API" leaves nothing to interpret. Rename existing invariants that fail this test, and update the test's own assertion message to say the stricter thing.

2. Put the rule where the caller will read it. A note in the owner module's header is invisible to someone editing a consumer. Either the constraint is visible at the point of temptation, or the language makes direct access impossible: private module, package-private path, unexported symbol, lint rule bound to the resource identifier.

3. Enforce with a repo-wide check, not a per-module test. A scan that fails when any file outside the owner names the resource catches the whole class, including modules that do not exist yet. A test living inside the owner module only proves the owner behaves.

4. Verify the gate runs on the path a change actually takes. An invariant test that only fires when someone runs the full local suite is not a gate. Confirm the automated pipeline executes it on every push to the integration branch. Prove it: break the invariant on a scratch branch, push, and watch the pipeline go red. If it stays green, the test was decorative.

5. Add a routing assertion to each consumer's own test file. Consumer tests normally assert behavior (the queue drains, the item is claimed) and pass regardless of how shared state was loaded. Add one assertion that the consumer obtained it through the owner API. That is the test whose failure lands in front of the person writing the bypass.

Review checklist for any change touching shared state:
- Does this code name the shared resource directly?
- If yes, is this file the owner?
- If not the owner, which owner call replaces the direct access?
- Is there a check that would have failed on this, and does it run automatically?
