---
id: re-enabling-a-switched-off-feature-must-not-revive-the-machi
kind: methodology
title: Re-enabling a switched-off feature must not revive the machinery that was retired
date: 2026-10-05
---

When a capability was turned off for a reason, and a later directive turns it back on, treat the two as separate decisions. 'Resume the output' does not mean 'restore the old producer'. A plan that lists the retired path as an intact asset, without asking why it was retired, will quietly bring back the thing the team chose to remove.

Three gaps let this happen, and each has a general fix.

1. Plan recon skipped the retirement history.
- Before choosing an implementation for a re-enabled feature, read the decisions that retired it. Ask what the retirement protected.
- Separate the directive's actual scope (cadence, autonomy, who has to approve) from the implementation it did not mention.
- If a stored lesson says 'do not add layers back', applying it is part of the plan, not optional context.

2. The invariant was only tested as a side effect of the switch.
- The test that guarded 'only one producer writes output' did so by asserting that the old entry points raise an error. When the feature was re-enabled, that test was inverted wholesale, and the invariant went with it.
- Write the invariant as its own test, independent of any on/off switch: 'every scheduled output is produced by the designated producer'. A switch flip then cannot delete the guarantee.
- When you invert a test, list what else it was asserting and move each of those claims somewhere that survives.

3. A producer's refusal was an implicit contract that a new input broke.
- The designated producer rejects a class of input on purpose, for example material it cannot attribute to the author, because every candidate from that class failed an earlier review.
- A new data source was then fed to it, and that source is made of exactly the rejected class: third-party text stored as isolated fragments.
- A downstream gate correctly blocked the result, which looked like a gate bug but was an input-contract mismatch upstream.
- Document each producer's refusals as part of its interface. Before wiring a new source in, check the source's shape against those refusals, and fail at the boundary with a message that names the mismatch.

Checklist when re-enabling something that was retired:
- Read why it was retired, not only what it did.
- Name the directive's scope in one line and keep the plan inside it.
- Add a contract test that does not depend on the switch.
- Check every new input against what the producer refuses.
