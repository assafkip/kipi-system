---
id: a-hand-copied-value-arrives-without-the-half-you-were-not-seeking
kind: pattern
title: A hand-copied value arrives without the half you were not seeking
date: 2026-08-11
---

One record held four facts about a channel: which days, which times, a length target, and an owner's directive reversing an earlier rule. Three were transcribed by hand into the consuming system, into constants, comments and a config file. The fourth was not. The record was named nine times across that codebase, every mention a comment, with zero reads at run time, so the directive sat unenforced for three weeks while the system kept behaving under the rule it had reversed. Nobody skipped it. Whoever copied was looking for timing and length, and found timing and length.

How to apply:

1. Treat a hand-copy as lossy by default, and lossy in a predictable direction: whatever you were not looking for. The copier's intent selects the fields, so the omission is invisible to the copier and to every later reader of the copy, since the copy looks complete on its own terms.

2. Read the whole source record before taking any field out of it, and write down what you are deliberately leaving behind. An explicit "not taking X because Y" survives; a silent omission becomes indistinguishable from an absence at the source.

3. Prefer reading the record at run time over transcribing values from it. Then a change at the source reaches the consumer without a human noticing, which is the property the transcription destroys. This is the whole difference between a dependency and a rumour.

4. When a boundary genuinely forbids the read, vendor the record as DATA the consumer loads, not as constants and prose. Vendored data can be re-synced, diffed and dated. A number inlined into code and a sentence quoted into a comment cannot be compared to their origin by anything but a person who remembers to look.

5. A comment naming a source file is not a dependency on it. Count the mentions against the reads before believing a system is informed by something: nine mentions and zero reads is a system that is talking about a file, not using it.

6. Suspect this first when a rule you know you changed is still being obeyed somewhere. The reversal usually did land; it landed in the record, and the record was never the thing being read.
