---
id: measure-the-thing-not-the-nearest-stand-in
kind: methodology
title: Measure the thing, not the nearest stand-in
date: 2026-08-10
---

Most wrong claims are not reasoning errors, they are substitution errors. You could not reach the thing the claim is about, so you measured the nearest reachable stand-in and reported it under the name of the real thing. A run of unrelated-looking false claims usually collapses into this single cause.

How to apply:

1. Before stating any finding, write one line for yourself: "claim X, measured Y." If X and Y are different nouns, the claim is unproven. Either go measure X, or restate the claim in terms of Y.

2. Measure through the path that actually runs. Offline copies, exports, snapshots and dev fixtures are stand-ins. Filters, transforms and defaults applied at runtime do not exist in the copy, so a count taken there is a count of a different population. Re-run the real entry point over the real input, then count.

3. Separate correlation from mechanism before naming a cause. When failing cases share an obvious surface feature, read the code path that decides the outcome and confirm that feature is a signal it actually reads. If it is not, the feature is coincidence and your fix will target nothing.

4. Test a join key before trusting a joined result. Count the rows the key fails to match. A high miss rate means you measured the key's coverage, not the phenomenon. Re-join on a second independent key and compare the two answers before concluding.

5. Publish the denominator with the number: "N out of M, where M is what I actually enumerated." A bare N hides the substitution; a stated M exposes it to anyone reading, including you.

6. Check a claimed gap against current state, not against the artifact that documents it. Lists, configs and notes describing what is missing go stale in the direction of overstating the gap, because entries are added when found and rarely removed when fixed.

7. When someone with direct knowledge contradicts your number, treat their version as more likely and re-measure before defending. A pattern of retracting only after pushback means the check that would have caught it never ran.

8. Convert the fix into an executable assertion, not an intention. One check that compares the derived count against the source-of-truth count kills the whole class. A resolution to be more careful kills none of it.
