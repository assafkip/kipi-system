---
id: address-peers-by-role-not-by-row
kind: pattern
title: Address Peers By Role, Not By Row
date: 2026-10-31
---

When autonomous workers can message each other, the address book is usually a flat list of live sessions, and some of those sessions are automation rather than peers. If a worker consults one of them, the automation answers conversationally, that reply becomes its final output, and the pipeline downstream of it parses an output that no longer contains the structured block it expected. The pipeline then emits a default or empty verdict, and a whole cycle of work is wasted while looking successful.

HOW:

1. Make automation sessions identifiable by name. Give every machine-initiated session a name following a reserved naming convention that encodes its role plus the artifact it is operating on. Reserve that shape so human- or agent-owned sessions can never collide with it.

2. Filter on the consulting side. Before sending any cross-session message, drop every candidate whose name matches a reserved automation shape. If the goal is to reach whoever owns a given artifact, resolve from the artifact to its owning session explicitly rather than pattern-matching whatever row happens to mention that artifact.

3. Disable the inbound channel on the automation side. Any session whose output is machine-parsed should run with cross-session messaging turned off, not merely discouraged. Capability removal beats convention: a worker that cannot be interrupted cannot be derailed by a well-meaning peer.

4. Validate structure before publishing. The consumer of a machine-generated output must assert the required structured section is present. A missing section is a malformed run, not an empty result. Never let absence collapse into a default verdict.

5. Make the malformed case retryable exactly once, pinned to the same input revision. Re-running on the identical input is safe and usually succeeds, since the derailment was transient. Pin the revision so the retry cannot silently grade different work, and cap at one attempt so a genuinely broken worker fails loudly instead of looping.

6. Fail loudly on the second miss. Surface a distinct error that names the malformed-output condition, so the failure is diagnosable rather than appearing as an ordinary negative result.

TEST: During a fixture run, deliberately send a peer-style message into the automated worker mid-flight, then assert the published output still contains the required structured section. This test fails under the naive design and is the only cheap way to catch this class of bug, because in normal operation the collision is rare and the symptom - a plausible-looking default verdict - is indistinguishable from a real one.

GENERALIZATION: Any time one process's free-form output is another process's structured input, you need two independent guards: isolate the producer from influences that can change its output shape, and have the consumer reject shapes it cannot parse instead of coercing them to a default. Either guard alone leaves a silent-wrong-answer path.
