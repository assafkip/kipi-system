---
id: check-what-is-already-on-disk-before-deciding-what-is-knowable
kind: pattern
title: Check what is already on disk before deciding what is knowable
date: 2026-08-11
---

The expensive failure is not missing data. It is having the data, reaching for a harder method, and then reporting a conclusion the unread file contradicts. It does not feel like an error while it happens: the harder method produces a real number with a real denominator, and a verdict of "not enough evidence" reads as rigour rather than as a failure to look.

Three times in one session on the same engagement, the answer was in a file already fetched, already parsed, and in two cases already opened that hour for a different field.

First, a question about whether an unlabelled number could be classified. Measured against labels inside the source text, the population was 2 and the verdict was INCONCLUSIVE, so a fix was parked. The client's own 536-row sheet, on disk, held 529 of those numbers hand-classified by a person who verifies each one against the supplier's report. Joining against it turned n=2 into n=207 and reversed the verdict outright.

Second, an "evidence floor" was then added to make that INCONCLUSIVE verdict more defensible. A floor on the wrong population is not rigour; it made a wrong answer look better defended.

Third, a message went to the client asking which staff names the system did not recognise. Every one of them was already in that same sheet's own staff column. The question did not need to be asked at all, and asking it spent the client's goodwill to retrieve something already held.

How to apply:

1. Before concluding that something cannot be determined, enumerate what is already on disk and name why each source does or does not bear on the question. "Not enough evidence" is a claim about the evidence you looked at, and it is only honest once that list exists.
2. Prefer the population a human already classified over any signal you would have to infer. A column someone typed after checking an authoritative source is ground truth; a pattern inside raw text is a stand-in for it.
3. Before asking a person for information, grep for it. A question you could have answered yourself costs their time and reads as inattention, which is worse than the delay.
4. Corroborate across independent collection paths rather than deepening one. Two sources that were gathered differently and agree is much stronger than one source measured harder.
5. When a verdict comes back INCONCLUSIVE or UNKNOWABLE, treat that as a prompt to re-examine the population, not as a finished answer. A tidy negative result is the most comfortable place for this defect to hide.
6. Watch for the tell: reaching for a new query, script or fetch while a fetched artifact sits unread in the working directory.
