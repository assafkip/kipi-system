---
id: don-t-optimize-a-generator-against-its-own-detector
kind: methodology
title: Don't optimize a generator against its own detector
date: 2026-07-06
---

When you have a checker that flags whether an artifact has some hard-to-define quality ("looks generic", "reads as low-effort", "feels off"), do not turn "pass the checker" into the generator's objective. The quality lives in a space that is effectively infinite and taste-bound; the checker samples a handful of points in it. Make the checker the target and the optimizer will satisfy those points while violating the spirit by construction. Every new tell you add is one more point it routes around. You cannot enumerate taste into a checklist, so a checklist can never be the spec for taste.

HOW TO APPLY:

1. Keep proxy and target separate. A detector is a floor (catch obvious failures), never the finish line. State in the spec that passing it is necessary, not sufficient. Do not feed the detector's rules back to the generator as instructions to satisfy.

2. Keep ground truth in the loop, before ship. The detector is a stand-in for a real judge (a human eye, a downstream metric, a market). If the only judgment that can see the quality you care about is consulted after the artifact ships, the proxy drifts unboundedly. Put the real judge inside the build loop: build -> real-judge review -> revise, with the detector as a cheap pre-filter, not the terminal check.

3. Don't ask a generator to escape its own priors by negation. "Do not look like your default" moves surface tokens (names, colors, wording) but not the underlying shape, because the shape IS the model's prior. Same generator, same defaults, regardless of the negative instruction. To get a genuinely different shape, change the input the generator reaches for (provide a concrete positive target, a different exemplar, a constraint that forces a different structure) or use a different generator. A negative instruction alone will produce variants that all rhyme.

4. Watch for the tell: outputs pass every automated check yet a human immediately clocks them as wrong. That gap is the signature of optimizing against the proxy instead of the target. The fix is not another detector rule (the loop is infinite); it is reinserting the ground-truth judge and giving the generator a positive target instead of a prohibition.
