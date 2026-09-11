---
id: when-feedback-keeps-becoming-rules-look-for-the-requirement-
kind: pattern
title: When feedback keeps becoming rules, look for the requirement with no home
date: 2026-08-17
---

Symptom: several rounds of correction on the same generated output, each round adding another constraint, and the next batch still fails the same way. Constraints accumulate; quality does not improve.

The mechanism: a pipeline that produces an artifact usually has a representable layer per concern (style has a config, correctness has validators, inputs have a queue). Whatever concern lacks a representation gets no fixes, because every rejection has to be filed somewhere, and reviewers file it into the nearest layer that can hold it. A style critique lands in the style config even when the real complaint was purpose. Over rounds this produces a growing pile of prohibitions that encode a requirement nobody ever wrote down.

How to detect it:

1. Take the last N rejections and classify each by the layer it was FILED into and, separately, the layer it was actually ABOUT. Divergence between the two columns is the signal. A single mislabel is noise; a consistent skew is a missing layer.
2. Count the ratio of prohibitions to positive specifications in the accumulated feedback. A body of guidance that is nearly all "never do X" and almost no "this output must accomplish Y for reader Z" means the positive form had nowhere to be stored.
3. Check the generator's entry point signature. List every parameter. If the concern people keep complaining about cannot be passed in at all, no caller could supply it even if one wanted to. An absent parameter is stronger evidence than any amount of reading of the surrounding code.
4. Grep for the identifiers of the context you suspect is missing and list which modules read them. If a context object is consumed only by neighbouring subsystems and never by the generating one, the two halves are severed regardless of living in the same repository.

How to fix it:

- Create the missing artifact first, as a file with a schema, not as a paragraph in a prompt or a comment. It must be readable, diffable, and reviewable on its own. Concerns without a file cannot receive corrections.
- Add the parameter to the generator's interface and thread the artifact through. Until it can arrive, the artifact is decorative.
- Replay the accumulated prohibitions against the new artifact. Each one either restates something the specification now covers (delete it) or is a genuine independent constraint (keep it). Expect a large fraction to be deletable; that fraction is the measure of how long the layer was missing.
- Change intake so a rejection must name the layer it belongs to before it can be recorded. If the named layer has no artifact, that is a blocking finding, not a line to append somewhere convenient.

Why each round felt reasonable: writing one more prohibition costs a line and requires no design; writing the missing specification requires deciding what the output is FOR, which is genuinely hard and is exactly the work the accumulating rules were substituting for. Cheapness is what makes the wrong fix win repeatedly.

Generalization: this applies to any system where an artifact is produced by one subsystem and judged by humans or another subsystem. Enumerate the layers a judgement can be about, then confirm each one has somewhere to live in code. The layer you cannot point at is the one absorbing every misfiled correction.
