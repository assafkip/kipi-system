---
id: verify-your-safety-guard-actually-covers-what-you-just-shipp
kind: methodology
title: Verify Your Safety Guard Actually Covers What You Just Shipped
date: 2026-10-19
---

When you build automation and also own a static check that is supposed to enforce a write-safety invariant (for example, 'nothing may write to the production target'), do not trust a passing result from that check. Treat it as a claim to be tested adversarially.

Method:
1. Separate the risk classes first. Decide whether non-determinism (such as a model in the write path) is even present. If the write path is fully deterministic, say so and move the integrity concern to where it actually lives: configuration, targets, and manual or one-off bulk edits.
2. Re-derive each invariant from the guard's own stated rules, then compare it against what the new code does in reality. Do not read the code back to itself; run something, such as the guard, a dry run, or a diff of actual writes, and record the output.
3. Enumerate every writer to each protected resource independently of the guard's registry. Count what the guard knows about versus what exists. A guard that only checks declared writers will report OK when undeclared ones are present.
4. Check for the two common gaps: new components never registered with the guard, and guard rules that inspect a name or a constant while the real destination is resolved elsewhere at runtime.
5. Quantify blast radius. Measure how many records the new automation touched and what other changes they overlap with, especially manual bulk edits that have no protection beyond backup or rollback files.
6. Fix by making the guard fail closed: unknown writers or unresolved targets should cause failure, new automation should be registered as part of shipping it, and any manual bulk change should be snapshotted before it is applied.

Takeaway: a green check only means the guard's model of the system passed. Verify that the model matches the system, especially right after shipping something new.
