---
id: make-empty-results-distinguishable-from-rejected-or-broken-o
kind: pattern
title: Make empty results distinguishable from rejected or broken ones
date: 2026-10-12
---

When a pipeline generates candidate findings, validates them, and then reports only the survivors, three gaps combine to make a total failure look like a clean, uneventful result.

1. Make the claim vocabulary able to express absence. If the proof types a validator accepts only cover things that are present (counts, matches, existence), the most valuable observations about missing data, checks that never ran, or fields that are never populated cannot be verified. The producer then either picks a proof that is bound to fail or drops the claim silently. Audit your domain's most common finding shape and confirm there is a verifiable way to assert it, including the case of a non-empty set with an empty field, not only the case where the whole result set is empty.

2. Never let the consumer render 'nothing found' from an empty list alone. An empty output can mean the stage found nothing, or it found several things and all were rejected, or it failed. Have the final report read the audit record of what was emitted, kept and rejected, and show distinct states for each, such as 'none found', 'N found, all rejected (reasons)', and 'stage failed'. Treat any path where correct work is computed, discarded, and then reported in a normal-looking shape as one defect class, and look for its other instances.

3. Measure and alarm on the keep rate. Record emitted versus kept counts for every filtering stage, and make something act on them: a threshold that flags or fails the run when the keep rate is anomalously low (especially zero with a non-zero input), a warning surfaced in the output, and a test asserting that a fully-rejected batch produces a visible signal. A metric that is written but never read does not protect anyone.

General test: for any stage that filters, ask 'if this rejected everything, would a reader of the final output be able to tell?' If not, add the distinction and the alarm.
