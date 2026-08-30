---
id: count-the-shape-in-the-corpus-before-you-widen-a-pattern-for-it
kind: methodology
title: Count the shape in the corpus before you widen a pattern for it
date: 2026-08-11
---

Widening a pattern to be "generous" feels free. It is not. Every alternative added to a pattern is a claim that the alternative occurs and that nothing else in the data looks like it, and both halves are checkable in seconds against the corpus you already have. Skipping that check is how a fix invents a defect while fixing one.

Observed 2026-08-11, in a single change. A parser needed to strip a deal separator glued to a customer name, `3#Barb Donaldson`. The first version accepted `#`, `.`, `)` and `:` as separators, and shipped with a test case reading `#2 Ann Boyle`. Counting the shapes in the message history took one command:

`N#Name` appeared 25 times. `#N Name` appeared ZERO times, so the test case had been invented rather than observed. `N) Name` and `N: Name` appeared zero times. `N. Name` appeared once, and the single occurrence was `1. Gig` — a PLAN line. Accepting the dot would have made "Gig" a customer name on the client's sheet, creating a new fabricated value while fixing fabricated values.

The pattern was narrowed to `#` alone, the invented test case was deleted, and a test now pins that `1. Gig` does not become a name. The narrowest pattern that covers the observed data was also the only safe one, and the corpus said so before any of it shipped.

The same session had already produced the matching failure in the other direction: a rule was skipped entirely on the argument that its shape occurred once in 530 messages. Frequency was the wrong test there, because the fix reused machinery that already existed and cost nothing new. Rarity is a reason to skip an EXPENSIVE fix, never a reason to skip a free one, and commonness is not what makes a widening safe — absence of look-alikes is.

How to apply:

1. Before adding an alternative to a pattern, count it in the corpus. Zero occurrences means you invented it; delete it rather than defending it.
2. Count what ELSE the widened pattern would now match. That is the number that matters, and it is where the new defect lives.
3. A fixture you wrote from imagination is not a test, it is a hypothesis with an assert. Build fixtures from real records and say which record each came from.
4. Ship the narrowest pattern that covers the observed data, and let a real counter-example widen it later. Widening is cheap to do once you have evidence; un-shipping a fabricated value from a client's sheet is not.
5. Rarity argues against an expensive fix, not a free one. Ask what the fix costs before asking how often it fires.
