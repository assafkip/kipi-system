---
id: pin-a-constraint-to-the-operation-it-forbids
kind: methodology
title: Pin a constraint to the operation it forbids
date: 2026-10-19
---

A constraint handed down in a brief is usually phrased as a prohibition on an outcome: do not go all the way to the end state, do not behave like a real user, do not touch the live system. The code that honors it has to decide something narrower: which call is allowed, how many hops, which responses get read. Those two statements are not the same, and the gap between them is filled by whoever implements it. Apply the prohibition one layer too early and the run still completes, still writes output, and still looks like a result. What it produces is empty of the exact thing the pass existed to collect, and volume makes that emptiness look authoritative.

How to work the first half:

1. Before implementing a stated constraint, rewrite it as a predicate over operations the code actually performs: this call, this many hops, this response body. If the rewrite cannot name an operation, the constraint is not implementable yet, and shipping it means guessing.
2. Name the harm the constraint protects against, then ask whether the operation you are about to forbid actually causes that harm. One resolution step performed by the service that owns an identifier is a different act from traversing all the way to a final destination, even though both read as "following a link".
3. Look for a primitive already in the codebase that encodes the safe version of the operation. If one exists, someone already drew this boundary once with the hard cases in mind; reuse it rather than inventing a stricter rule in prose.
4. Establish where the target data actually lives before you restrict how to reach it. If the payload only exists after a resolution step, a rule forbidding that step has made the pass structurally incapable of succeeding, and no amount of scale will reveal it.

The second half is sequencing. Known-answer controls are worth nothing while they sit behind the finish line of a long pass. Existing on disk is not the same as having fired.

5. Evaluate the controls on the first small slice, not in the summary step. Process a handful of items, check the cases whose answer is known in advance, and release full volume only after they hit.
6. Make control evaluation callable on a partial result, independent of the report writer. If the only code path that checks a known answer is the final summary builder, every control is a post-mortem by construction, no matter how good the control is.
7. Put a plausibility floor on the partial result as well. If a count or rate on the first slice is far from what the domain says it should be, stop there. A long run reproduces the same wrong number with more digits and more apparent confidence.

The pairing matters: a misplaced constraint is invisible to review because the sentence in the brief and the sentence in the code read the same. A control on the first slice is what turns that invisible substitution into a visible contradiction, before the expensive part runs.
