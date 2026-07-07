---
id: port-the-mechanisms-not-the-words-that-describe-them
kind: pattern
title: Port the mechanisms, not the words that describe them
date: 2026-07-06
---

When you reimplement a working system somewhere new, the value lives in its deterministic machinery, not the prose that narrates it. A mature tool earns its results from concrete primitives: cost-ordered escalation tiers, parallel first-pass plus a merge/dedup step, an ordered checklist with a weighted coverage or depth score, per-input-type triggers that decide when a result is confident enough, contradiction and collision checks, and a coordinator that orchestrates rather than does the work itself. The stopping condition is 'quality met,' not 'inputs exhausted.'

The failure mode is a doctrine-to-prose translation: you copy the persona, the phase names, and the descriptive guidance, then hand the actual decisions to one model's free judgment. That produces non-reproducible, recall-led runs whose output varies every time and can silently disconnect. Keeping the vocabulary while dropping the mechanisms feels like a port because the surface reads the same; it is not one.

How to do it instead:

1. Before porting, inventory the SOURCE as a list of mechanisms, not phases. For each phase-description, ask: what deterministic primitive backs this — an ordering, a merge, a threshold, a checklist, a score, a guard? If a phase has no backing primitive, it was already prose.

2. Port each mechanism explicitly, one at a time, and verify it exists in the new implementation with a per-mechanism gate. A re-read of the new code proves nothing; the check is 'this primitive is present and produces the same shape of decision.'

3. Preserve the stopping condition. If the source stops on a quality threshold, the port must too — replacing it with 'ran out of inputs' or 'model decided it was done' is the most common silent drop.

4. Keep orchestration and execution separate. A coordinator that starts doing the work itself is a sign a mechanism collapsed into free judgment.

5. Treat any belief that 'the source didn't really have that mechanism' as a claim to verify against the source code, not an assumption. A false 'it was vaporware anyway' licenses dropping exactly the primitives that made it work.

The test of a real port: same inputs give reproducible, mechanism-driven output, and every primitive the source relied on has a named counterpart you can point to.
