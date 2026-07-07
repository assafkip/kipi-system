---
id: for-a-read-only-artifact-done-is-the-render-not-the-write
kind: pattern
title: For a read-only artifact, done is the render, not the write
date: 2026-07-06
---

When a field, record, or artifact exists so that something downstream will read it and surface it, "the value is produced and populated" is not a valid definition of done. The value only exists to be consumed; if nothing consumes it, it is dead data that satisfies every producer-side check while delivering none of its purpose.

**Three failure modes that let write-only data ship, and how to close each:**

1. **Acceptance criteria name only the producer.** If every clause says "add the field / populate it / validate what was written" and no clause says "X reads it" or "the output shows it," the spec is satisfiable by data that is never surfaced. Fix: for any field whose value is to be displayed or consumed, write at least one acceptance clause on the CONSUMER — "the rendered output contains the trace" — not just on the write.

2. **The test is the only reader.** A test that reads a field to assert it was populated cannot tell "used in production" from "used only by this test." It goes green precisely because the test itself is the sole consumer. Fix: assert on the artifact the user actually receives (the rendered report, the response payload, the exported file), not on the intermediate field. If no such assertion exists, no gate can notice the value never reaches output.

3. **The wiring/definition-of-done check runs at session end, not per field.** A rule that says "every new field needs both a producer and a consumer" only helps if it fires when the field is added. A once-at-the-end pass is easy to skip and easy to forget a single field in. Fix: apply the producer-AND-consumer check at the moment each read-only field is introduced.

**The reusable heuristic:** before calling a data-carrying change done, name the specific reader that turns the value into something a human or downstream system observes. If you cannot name a reader outside your own tests, the field is not wired — regardless of how green the suite is.
