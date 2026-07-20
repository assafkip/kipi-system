---
id: a-cross-process-handshake-needs-one-source-and-a-test-that-p
kind: pattern
title: A cross-process handshake needs one source and a test that pins both ends
date: 2026-07-20
---

When two processes must agree on a shared key (a correlation id, a run id, a session token), the failure mode is silent: a producer writes under one value and a consumer reads under another, so the store looks empty and nothing errors. It happens whenever each side derives "the same" logical value from a different source — one reads an environment variable, the other parses it out of the payload it received — because two independent derivations are two independent guesses, and nothing forces them to match.

HOW:
1. Name one authoritative source for the shared key and have the other side receive it, not re-derive it. Pass the value across the boundary (in the payload, on the command line, through a named handle) rather than letting each end reconstruct it from ambient state. One producer, one channel, one value.
2. If a side must read the key from the environment or an external handle, treat that name as a contract, not an assumption: verify at runtime that the variable/field is actually populated by the system you run under, and fail loudly (not silently to empty) when it is absent. An unverified variable name is an untested integration point.
3. Pin both ends with a single test that exercises the real handoff: producer writes, consumer reads, assert the consumer recovers exactly what the producer wrote. A test that stubs one side proves nothing about agreement — the whole defect lives in the gap between the two sources, so the test has to span it.
4. Prefer a shape where a mismatch cannot be silent: make the consumer assert the key is present and non-default before it does its work, so a broken handshake surfaces as a hard failure at the boundary instead of an empty result far downstream.
