---
id: a-per-item-stage-multiplies-whatever-runs-downstream-of-it
kind: pattern
title: A per-item stage multiplies whatever runs downstream of it
date: 2026-08-17
---

When a pipeline runs a stage once per input item, anything chained behind that stage runs once per item too. If the downstream step is an independent fetch, its results come back multiplied by the number of items upstream. The failure mode is quiet: every record in the output is real and well-formed, so nothing looks corrupt. Only the count is wrong, and a count is exactly the thing that reads as data rather than as a bug.

How to avoid it:

- Fan independent fetches out from the trigger in parallel. Chain only when the second step genuinely consumes the first step's output. "It reads naturally in sequence" is not a data dependency.
- Before drawing any conclusion from a collection, check its size against what the source should hold. If the source has N records and you have a multiple of N, you have a fan-out bug, not a discovery.
- Treat a suspiciously round multiple (2x, 5x, exactly the item count) as the primary hypothesis, not a coincidence.
- Assert expected cardinality where the data lands, so the multiplication trips a check instead of surviving into a report.
