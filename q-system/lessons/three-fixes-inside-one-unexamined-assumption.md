---
id: three-fixes-inside-one-unexamined-assumption
kind: methodology
title: Three fixes inside one unexamined assumption
date: 2026-08-11
---

A content system produced output its owner rejected as boring. It was fixed three times over six days, each fix correct, each one verified, and the output stayed boring. The first fix widened a starved supply from eleven stale files to a live one. The second swapped that supply from git commits to recorded rules and postmortems, on the correct reasoning that a commit is a change while a rule is a consequence. The third removed a prompt rule that was forcing every post into the same sentence shape. All three landed. None of them helped, because all three were made inside an assumption nobody had stated: that the system writes about itself. The supply was 68 internal operating rules, 10 postmortems of its own crashes, and 4 of its own problem statements. Not one item concerned the world the reader lives in.

How to apply:

1. When the same complaint survives two fixes, stop fixing and go find the sentence nobody has said out loud. A defect that outlives its repairs is usually not a defect at that layer at all. Each repair was a correct answer to a question that was one level too shallow.

2. Write down what the fix is holding constant. Every change has a frame it does not touch, and the frame is invisible precisely because every participant shares it. "We improved the format of what we say about ourselves" and "we improved what we say" are different claims that sound identical from inside.

3. Distinguish the shape of a thing from its subject. Format fixes are tractable, measurable and satisfying, so they get made first and get made repeatedly. They cannot reach a problem whose cause is what the material is about. If the measurements improve and the judgment does not, you fixed shape and the problem was subject.

4. Ask what the input can possibly produce, before improving how the input is processed. A closed internal corpus can only yield internal stories, however well written. No downstream rule, gate or prompt can add a subject the source material never contained.

5. Treat a finite source as a countdown, not a supply. A fixed corpus is consumed at a known rate, and the day it empties the system reaches for whatever is next in priority, usually silently. Know how many items remain and what happens after.

6. Count the repetitions honestly and name the number. "This is the third time" is a different argument from "this happened again", and it is the one that gets the frame examined rather than the mechanism patched a fourth time.

The tell is a series of correct fixes with no cumulative effect. Correctness at the wrong altitude reads exactly like progress right up until someone reads the output.
