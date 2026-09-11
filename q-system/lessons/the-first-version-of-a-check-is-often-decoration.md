---
id: the-first-version-of-a-check-is-often-decoration
kind: pattern
title: The first version of a check is often decoration; mutation finds it
date: 2026-09-02
---

Across 29 issues the mutation proofs found, again and again, a test that could not fail for the reason it claimed: an `or True` in a fan-out test, an assertion on the word "symlink" that the tmp path itself satisfied, a source-grep a comment could satisfy, a selector that matched no tests, an equivalent mutant hiding behind a second check. Every one was fixed by asking which input makes it red. prd-morning-brief-learns and prd-lessons-rail-and-up-rail, 2026-09-01 to 02.

How to apply:

1. After the suite is green, break the code the way the finding described and watch the test die. A survivor is either an equivalent mutant (write down why) or a test to rewrite.
2. Keep the mutation script beside the issue; rerun it after every review fix, because fixes move the anchors.
