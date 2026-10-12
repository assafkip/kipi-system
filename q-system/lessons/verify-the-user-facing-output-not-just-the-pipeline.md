---
id: verify-the-user-facing-output-not-just-the-pipeline
kind: methodology
title: Verify the user-facing output, not just the pipeline
date: 2026-10-12
---

When declaring work done, prove the claim at the surface the stakeholder actually reads, not only at the machinery that produces it. Internal receipts (job succeeded, tests green, change merged, review passed) show that the pipe works; they do not show that what comes out is true.

How to apply it:

1. Define done as the stakeholder's contract. Write down, in the stakeholder's terms, what must be true of the final output (for example: 'the summary shows no stale items and no false obligations'). Do not substitute a plan you wrote yourself, because then you are grading your own homework. If the contract is implicit, make it explicit and turn it into a check.

2. Before reporting completion, render the real output and compare it line by line to the underlying evidence. If a command exists that produces the output, run it and read the result against the source data. This is usually cheap.

3. Add a test at the level of the output, not just the component. Per-item rules can all pass while the aggregate, such as a per-relationship or per-page view, is wrong. Assert that each rendered line is supported by its evidence.

4. Build fixtures from real failing cases, not only synthetic ones. Synthetic pairs confirm the logic you imagined; live failures reveal the cases you did not. When a bug is found, add the real instance as a regression fixture, and check sibling filters or categories for the same gap.

5. Apply the 'first run proves nothing' rule to every layer. Clean runs of an upstream job do not validate downstream output. Require repeated, independent confirmation on the final surface across more than one cycle.

6. Treat repeated feedback as a signal for a gate. If a stakeholder corrects the same kind of miss twice, convert the correction into an automated or checklist step rather than only acknowledging it.

Rule of thumb: evidence about the process is not evidence about the product. Before saying 'done', look at what the user will look at.
