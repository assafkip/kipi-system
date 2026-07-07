---
id: verify-a-port-with-a-mechanism-by-mechanism-gate-not-a-re-re
kind: methodology
title: Verify a port with a mechanism-by-mechanism gate, not a re-read
date: 2026-07-06
---

When you re-implement a body of behavior that already exists in an authoritative reference (a prior system, a spec, a codebase you are porting from), "parity" is a claim that must be proven mechanically, not asserted by reading both sides and judging them equivalent. A human re-read of source and target is exactly the check that misses the one mechanism silently dropped, weakened, or subtly diverged.

How to do it:

1. Enumerate the reference's mechanisms as a flat list before writing any target code. Each row is one discrete behavior: a scoring rule, a resolution step, a guard, an escalation order, a merge/dedup pass. Name them so each maps to exactly one thing on each side.

2. For every row, write a target-side assertion that proves the mechanism is present AND behaves the same: it exists, it fires on the inputs that should trigger it, and it produces the reference's outcome. Presence alone is not parity; a stub that never fires passes a grep and fails the behavior.

3. Collect those assertions into a single deterministic gate that runs on demand and reports N-of-M with each row labeled ok or not. The gate is the artifact of record, not the prose comparison. "I read both and they match" is not done; "the gate asserts all M and returns all-ok" is done.

4. When the target is intentionally stricter or divergent from the reference, encode that as an explicit assertion too, so the divergence is a recorded decision rather than an unexplained mismatch a future reader must re-litigate.

5. A mechanism you cannot yet assert stays visibly staged in the gate (counted, marked not-ok), never quietly assumed equivalent. The gap is tracked, not forgotten.

The payoff: parity becomes a rerunnable pass/fail you can re-prove after any later edit, instead of a one-time reading that decays the moment either side changes.
