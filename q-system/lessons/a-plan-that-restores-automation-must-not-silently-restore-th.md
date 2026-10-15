---
id: a-plan-that-restores-automation-must-not-silently-restore-th
kind: methodology
title: A plan that restores automation must not silently restore the retired component it ran on
date: 2026-10-04
---

When you re-enable an automated capability that was switched off, the plan tends to treat everything in the old path as a reusable asset. That conflates two separate decisions: whether the work runs automatically, and which component does the work. A retirement usually carries its own reasoning, and the plan that revives it needs to find that reasoning first.

Three failures stack in this pattern.

1. Recon lists the retired path as intact and never asks why it was retired. Before choosing a component for a re-enabled flow, re-read the earlier decisions that consolidated or removed it. A directive about cadence or automation says nothing about which implementation to use. Check durable notes and prior decisions for guidance such as 'do not re-add layers' before the plan commits.

2. The single-writer contract was only covered as a side effect of the on/off switch. The old test asserted that the retired entry points raised errors. When the feature was re-authorized, that test was inverted wholesale, and nothing remained to assert the independent invariant that every scheduled item is produced by the one sanctioned writer. Turning the switch on turned the second path back on without a single red test. Give each architectural invariant its own test, separate from the feature flag, and when you invert a test during a re-enable, ask which invariant the old assertion was also guarding.

3. A lane that refuses a class of input on purpose has an implicit contract with every feeder. An earlier review had rejected external material for that lane because it could not be attributed to the author or connected without pitching. A new input bank was external by construction, was fed in as the writer's own material, and a downstream gate then correctly refused to narrate a stranger's work in the author's first person. Write the lane's accepted input classes down as a checked contract, and have every new source declare its class so a mismatch fails at integration instead of at the output gate.

Checklist when reviving something turned off:
- Find the retirement decision and state why it happened.
- Separate 'run automatically' from 'run the old implementation'.
- Add a test for each invariant that the old off-state was implicitly enforcing.
- Verify every new input source against what the consuming lane accepts.
