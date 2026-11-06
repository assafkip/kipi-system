---
id: attributing-failures-in-staged-generation-pipelines
kind: methodology
title: Attributing Failures in Staged Generation Pipelines
date: 2026-11-01
---

## When to use
Every item in a staged pipeline (source record -> derived spec -> generator -> validator) is being rejected, and the only visible evidence is the validator's rejection text. Use this to find out *which stage* owns each failure before changing any code.

## How

1. **Split surface from structural cause, per item.** Build a table with one row per failing item and two columns: the verbatim rejection message (surface) and the stage whose behavior made that message inevitable (structural). Never let a rejection string stand as the diagnosis — it is an output of the last stage, not evidence about where the defect lives.

2. **Spend zero generator calls on hypotheses you can measure.** Before any paid or slow run, dump the intermediate artifacts and inspect them directly for the content you suspect is missing or malformed. Record the outcome as "ruled out by measurement, no generation calls" together with what you inspected, so the same hypothesis is not re-litigated later.

3. **Enumerate the stages and test each one explicitly.** For a four-stage chain, that means testing the source record, the derived spec, the generator, and the validator as four separate suspects. Label every failure by stage, not by symptom.

4. **Group failures into named classes and count members.** Fix classes, not items. Common classes in generation pipelines: the generator inventing unsupported detail to fill gaps; the source record being mismatched to the requested output type; the validator failing structurally so nothing was graded at all; a hard size or format constraint making the acceptance criterion unsatisfiable.

5. **Treat validator malfunctions as a distinct, higher severity.** If the validator returns malformed or unparseable output, the item was never actually evaluated — its "rejection" carries no information about generation quality. Repair or retry-wrap that path first; until then, do not interpret any other result from those items.

6. **Hold everything fixed but one axis when comparing variants.** Compare generator variants against a byte-identical spec and an unchanged validator, varying one dimension at a time. In the writeup, state explicitly which gates or checks you did **not** re-run, so readers do not over-read the comparison matrix.

7. **Cap the re-run set and say so.** Declare the cap up front, and mark the untested remainder as "not re-run; same failure classes" rather than silently generalizing from the sample or silently dropping the rest.

8. **Check for unsatisfiable criteria.** If a length, format, or budget constraint leaves no room to satisfy the acceptance rule, the defect is in the constraint or the rule, not in the generator. Verify this arithmetically before tuning prompts.

9. **Re-attribute after each upstream fix.** Removing one blocker commonly transfers ownership of the remaining failures to a different stage. Close each round with an explicit sentence of the form "failures now belong to stage X, not stage Y," and re-run step 1.

## Pitfalls
- Reading the rejection text as the root cause.
- Tuning the generator when sparse or mismatched input is the real cause.
- Running expensive comparisons before exhausting free, measurable checks.
- Publishing a comparison matrix without stating what was held constant and what was skipped.
- Assuming a fix landed because the original symptom disappeared, when the same count of items is still failing for a new reason.
