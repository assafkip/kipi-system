---
id: author-per-constraint-variants-from-the-source-idea
kind: pattern
title: Author Per-Constraint Variants From The Source Idea
date: 2026-11-06
---

When the same idea must ship into multiple targets whose constraints differ sharply (tight length or size limits, different idioms, different conventions), do not derive the constrained version by truncating or stripping the unconstrained one. Instead, go back to the underlying idea and author a fresh version natively inside each tight constraint.

How to apply it:

1. Capture the idea once in a neutral, source-of-truth form: the core claim, the supporting point, the intended action. Keep this separate from any output artifact so no single output becomes the de facto master.

2. Group targets by how binding their constraints are. Targets with generous limits and similar conventions can share one rendering of the brief. Targets with hard, aggressive limits get their own authored version.

3. For each hard-constrained target, write from the neutral idea while already inside that target's limit and idiom, rather than writing long and then cutting. Compose to the budget from the first draft so structure, ordering, and emphasis are chosen for that constraint instead of inherited from a different one.

4. Validate against the constraint mechanically (automatic length[PATH] check) and against quality separately, so a version that merely fits is not mistaken for one that works.

5. Compare outcomes between natively authored versions and reduced ones using whatever success signal the target exposes. Keep the split where the authored versions measurably win; collapse it back to a shared rendering where they do not, so you are not paying duplication cost for no gain.

Why it works: reduction preserves the skeleton of the original constraint and only deletes material, so the result carries structure that was never designed for the new limit. Authoring inside the limit lets you pick a different skeleton entirely.

Failure modes to watch: treating the longest output as the canonical source (which silently makes every other target a degraded copy); splitting every target instead of only the hard-constrained ones (duplication cost with no benefit); and letting independently authored versions drift apart on substance, which the neutral source-of-truth form plus a review pass across versions is meant to prevent.
