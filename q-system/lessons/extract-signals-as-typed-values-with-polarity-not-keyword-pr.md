---
id: extract-signals-as-typed-values-with-polarity-not-keyword-pr
kind: pattern
title: Extract signals as typed values with polarity, not keyword presence
date: 2026-07-06
---

When you pull signals out of text or logs, model each one as a typed value with explicit polarity — present, absent, or unknown — not as a bare keyword that either appears or does not. A keyword match only tells you the topic was mentioned; it cannot tell you whether the source asserted the signal or denied it. In any layer that also shows or reasons over the surrounding prose, the signal's own name routinely co-occurs with its negation ("no <signal>", "<signal>=false", "cleared of <signal>"), so a name-only check flips a clean case into a hot one.

HOW to apply:

1. Parse the value, not just the token. Read the field's actual value (flag=false, status: none) before you let the presence of the field name mean anything. Treat generic word-in-prose matches as unsafe in any report or decision layer — the word and its negation live in the same sentence.

2. Give every extracted signal three states, not two. Positive, negative, and unknown are distinct. Collapsing negative into "absent" or into "positive-because-mentioned" is the defect. Downstream logic keys off the typed state, never off whether the string was found.

3. Make the polarity requirement explicit in the contract. "Extract the categories" is under-specified; the real requirement is usually "extract typed evidence with polarity." If the spec is silent on how negation is handled, that silence is a gap to close before coding, not a detail to infer.

4. Test the inverse path, always. A reproducer that only proves a positive input is flagged positive lets the negated case rot undetected. For every positive assertion, add its mirror: an explicit negative input must stay negative, and an ambiguous one must land in unknown. The absence of the inverse test is what lets a broken implementation pass acceptance while silently mangling clean inputs.

The smell: any classifier or scanner whose correctness depends on a substring or word-presence check over text that can contain the negation of what it is looking for.
