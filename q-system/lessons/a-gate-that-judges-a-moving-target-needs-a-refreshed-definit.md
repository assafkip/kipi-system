---
id: a-gate-that-judges-a-moving-target-needs-a-refreshed-definit
kind: pattern
title: A gate that judges a moving target needs a refreshed definition and full-dimension coverage
date: 2026-07-06
---

When a check classifies something against a definition that drifts over time — what counts as "typical," "default," "spam," "machine-generated," "trending," or "suspicious" — the definition is not a constant. Encoding it as a hardcoded literal (an inline array of tells, keywords, signatures, thresholds) guarantees the check is one generation behind: the day the real-world pattern shifts, the literal is stale, and the gate keeps policing the old shape while going blind to the new one. Three moves keep such a gate honest.

First, separate the definition from the code. The list of what-to-flag is data with a lifespan, not a constant. Store it where it can be updated without editing detection logic, and treat 'this list must reflect the present' as an explicit contract, not an assumption.

Second, give the definition a mechanism to learn what it currently means. A list that only changes when a human remembers to hand-edit it will drift silently and forever. Build a process that observes what the target actually looks like now — sample real current inputs, weight by a trailing window so recent reality dominates, and record provenance so a stale definition is detectable rather than invisible. Without an observation loop, decay is guaranteed and unannounced.

Third, cover every dimension the target can shift along, not just the ones that were salient when you first wrote the check. A classifier that inspects some axes but leaves a whole class of signal uninspected has a permanent blind corridor — and a moving target will eventually move exactly down the axis you never measured. Enumerate the dimensions the signal can live in and confirm each is actually read.

The general shape: a gate against a drifting definition fails not by being wrong once, but by being frozen. Refreshable definition + observation loop + full-dimension coverage is what keeps it tracking reality instead of a snapshot of the past.
