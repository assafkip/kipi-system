---
id: kill-a-defect-class-by-deleting-the-mechanism-not-by-guar
kind: pattern
title: Kill a defect class by deleting the mechanism, not by adding a guard to it
date: 2026-08-05
---

When successive review rounds keep finding NEW defects of the SAME class in the same code, each round is guarding one more instance of a class rather than removing the class. The signal is not "these are hard bugs"; it is that the mechanism producing them should not exist.

Observed on a rule that decided an exemption by inferring a date from mutable, strippable state. Three separate hardenings shipped: first on one mutable field, then on a different identifier's embedded date, then on the format of that date. Each fix was correct about the instance it addressed and each left the class alive. A code comment written during the second attempt openly recorded that the inference was undecidable, and the third attempt was built on top of that admission. The resolution was to delete the exemption mechanism entirely so the rule consulted no date at all, which retired all three hardenings at once.

The counter-case matters as much: deleting a mechanism is only correct when the thing it protected turns out to be unnecessary or obtainable another way. Measure that before deleting, rather than assuming.

How to apply:

1. Track defects by CLASS across rounds, not by count. Three findings that share a root cause are one signal about a surface; three unrelated findings are ordinary review. Only the first justifies restructuring.
2. Distinguish self-inflicted from independent. A round finding a defect INTRODUCED by the previous round's fix means the loop is generating work faster than it removes it, and grinding is the wrong response. A round finding another pre-existing defect means review is working through a dense surface, which is review functioning.
3. Before deleting a mechanism, measure what it actually protected. Enumerate the cases it currently exempts or handles, and confirm they are either unreachable or covered elsewhere. A deletion justified by argument rather than measurement is a new defect.
4. When you do delete, delete the whole apparatus: the helper, its constants, its tests' reliance on it. Leave a test asserting the names stay gone, so a later change cannot quietly reintroduce the mechanism.
5. Decide the restructure BEFORE the next round's verdict arrives. Deciding after means the verdict shapes the decision, and a clean round is not evidence of sufficiency for a class that has produced a defect every round so far.

The general contract: a guard added to a bad mechanism inherits the mechanism's failure modes. Removing the mechanism is the only fix that cannot be followed by another instance of the same class.
