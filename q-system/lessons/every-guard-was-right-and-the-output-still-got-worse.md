---
id: every-guard-was-right-and-the-output-still-got-worse
kind: methodology
title: Every guard was right and the output still got worse
date: 2026-08-11
---

A generator grew from two executable checks to fourteen in six days, each one a real test or validator, and its instruction file tripled alongside them. Every addition had a genuine failure behind it, documented in the comment above it, and each one measurably stopped its defect from recurring. The output over the same period became something the owner rejected outright. No executable in the loop had ever asked whether the result was good, only whether a known defect had reappeared, and on that question every one of them was passing the whole time.

How to apply:

1. Name the thing you are optimising before you add the guard, then check it is the thing you care about. "This defect does not recur" and "the result is good" are different objectives that feel identical while you are adding the third check and diverge badly by the fourteenth.

2. Count the checks that judge quality versus the checks that judge defects. If the second number is growing and the first is zero, more checks will not help, and each one narrows the space the work can move in.

3. Watch for a constraint that resolves a failure by forbidding a shape. Forbidding is cheap and precise, so it wins arguments, and a stack of shape prohibitions eventually specifies exactly one output. Prefer a constraint that says what to do over one that says what not to do; if you can only articulate the prohibition, you have not understood the failure yet.

4. Re-read the accumulated instructions as one document, periodically and out loud. Rules added one at a time to fix separate incidents contradict each other, and the contradiction is invisible in every individual diff. Two rules 50 lines apart, one mandating a shape and one forbidding it, both looked correct when they landed.

5. When a guard fires constantly and is overridden constantly, it is not a guard. Either it encodes a standard nobody actually holds, in which case retire it, or it encodes one people keep violating, in which case it should block. A permanent advisory teaches everyone to skim exactly the channel you would use to say something urgent.

6. Prefer removing a constraint over adding one when the complaint is about quality rather than correctness. The instinct runs the other way, because addition feels like progress and deletion feels like giving up ground that was won for a reason.

Each guard being individually defensible is what makes this hard to see: there is no bad decision to find in the history, only a missing question.
