---
id: re-enabling-automation-must-not-revive-a-retired-implementat
kind: methodology
title: Re-enabling automation must not revive a retired implementation, and contracts need their own tests
date: 2026-10-19
---

When a capability is switched back on, three failures can combine to bring back a component that was removed on purpose.

1. Separate the goal from the mechanism. A directive such as 'run this automatically' describes the goal (cadence, no human in the loop). It does not choose the implementation. Before planning, write the goal in one sentence and list separately the mechanisms that could meet it. Treat a 'retired but intact' component as a suspect, not an asset. Find out why it was retired by reading the earlier decision records, resets and consolidation decisions, and recorded team guidance, before any plan reuses it. Add a plan checkpoint: 'Which earlier decisions constrain this choice, and did I re-read them?'

2. Give each invariant its own test. If an invariant (for example, 'every output is produced by one designated producer') is only checked indirectly through a guard on a different feature, such as a kill switch that raises an error, then re-enabling that feature will rewrite or invert the test, and the invariant goes unchecked. For each important architectural decision, write a positive test that holds whether the feature is on or off, such as 'every scheduled item comes from producer X.' When you must invert a test, list which invariants it was protecting and confirm each one still has a test.

3. Write down the implicit input contract. A pipeline may refuse certain inputs on purpose, for example third-party content that cannot be honestly attributed to the author. Before wiring a new data source into it, check whether that source belongs to the refused class. If it does, expect downstream gates to reject it, or redesign the source's role (for example, as a topic prompt rather than as source material) instead of forcing it through. Record each deliberate refusal with its rationale next to the code, and have the type or interface enforce it where possible, so a later integration meets the rule at the boundary and not through late, confusing gate failures.

Check before re-enabling: (a) goal and mechanism written separately, (b) prior decisions that explain any retired parts re-read, (c) each invariant covered by a test independent of the feature toggle, (d) each new input source checked against the pipeline's deliberate refusals.
