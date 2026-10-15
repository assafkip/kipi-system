---
id: verify-the-user-facing-output-not-the-machinery-that-produce
kind: methodology
title: Verify the user-facing output, not the machinery that produces it
date: 2026-10-05
---

A task can pass every internal gate and still fail the person it was for. Gates, receipts, green test suites, merged changes and job-success stamps all describe the machinery. They say the pipe ran. They do not say the water is clean.

Three habits produced the miss, and each has a fix.

1. Define done at the surface the consumer sees. Before declaring completion, run the cheapest command that renders the real output and compare it line by line against the underlying evidence. If a renderer exists and costs one command, running it is the minimum bar. Reading the output is the verification, not reading the receipts.

2. Separate the stated goal from the plan you wrote. A plan authored by the same agent that executes it grades its own homework. Write the consumer's contract as an explicit, checkable statement of what true looks like on their surface (fresh, honest, no stale items, no false obligations). Then test the finished output against that statement, not against the plan's step list. If the user has already said "that is what I asked for" once, the contract is being missed. Capture it as a check, not a note.

3. Add tests that compare rendered output to its evidence. Per-item tests can pass while the aggregate lies, because a rule that is right for each record can still be wrong at the level the reader sees. Build fixtures from real failing pairs from production, not only synthetic ones. For every filter, test every state that should exclude an item (deferred, parked, snoozed), not just the states you thought of first.

4. Apply the first-run-proves-nothing rule to the output, not just the job. Two clean runs of the producer are not a day-two proof of the rendered result. Require the surface itself to be inspected across at least a second cycle before closing.

Short form: prove the claim at the level the claim is made. If you say the user's view is correct, the evidence is the user's view.
