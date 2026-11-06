---
id: calibrate-automated-rules-against-labeled-examples
kind: methodology
title: Calibrate Automated Rules Against Labeled Examples
date: 2026-11-06
---

When you convert a subjective guideline into an automated check (a lint rule, regex, validator, heuristic, or model-based classifier), do not deploy it on the strength of its logic alone. Measure it against examples you have already judged by hand.

HOW:

1. Build a small labeled corpus first. Collect items you previously rejected (should be flagged) and items you previously accepted (should pass). A few dozen of each is enough to expose gross failures; even 5-10 per class will reveal a check that does nothing.

2. Store the corpus as fixtures next to the check, one item per record, with the human label and a one-line reason. Keep the original wording or input untouched so the check sees exactly what a human saw.

3. Run the check over the corpus and record four counts: caught rejects (true positives), missed rejects (false negatives), falsely flagged accepts (false positives), and cleanly passed accepts (true negatives).

4. Read the two error columns separately, because they have different costs. A check that catches none of the known-bad items provides zero protection while creating the illusion of coverage. A check that flags most known-good items will be disabled or ignored by its users within days, which also leaves you unprotected.

5. Set an explicit pass bar before you look at the numbers, so you cannot rationalize a weak result. A reasonable default for an advisory check is: catches a clear majority of known-bad items and flags almost no known-good items. For a blocking check, demand a near-zero false positive rate, since every false positive stops legitimate work.

6. Iterate on the rule, not the labels. If the check misses an item, ask what signal a human used that the code cannot see. Often the guideline you encoded is a proxy for something else, and the honest conclusion is that this particular rule cannot be automated as written. Narrow it to the subset it handles reliably rather than keeping a broad rule with poor accuracy.

7. Freeze the corpus run as a test. Assert the expected counts so later edits to the rule cannot silently degrade it. Append new items to the corpus every time a human judgment disagrees with the check in production.

8. Record the measured hit rate wherever the check is documented, and surface it in the output when the check fires. Downstream users should know whether a warning is near-certain or merely suggestive so they can weight it correctly.

WHY THIS MATTERS: an unmeasured check is worse than no check, because teams stop looking for the problem it claims to cover. The calibration step converts an assumption about your rule into a number you can defend, and it frequently reveals that a rule that reads perfectly well catches nothing at all.
