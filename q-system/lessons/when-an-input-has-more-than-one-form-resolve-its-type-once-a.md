---
id: when-an-input-has-more-than-one-form-resolve-its-type-once-a
kind: pattern
title: When an input has more than one form, resolve its type once and honor it at every consuming stage
date: 2026-07-06
---

# The trap

An input can arrive in more than one shape that means different things (a remote address vs a local reference, an absolute vs relative locator, an inline value vs a pointer to fetch). One stage of the pipeline learns to tell the shapes apart. A later, independent stage assumes only one shape and acts on it blindly. Each stage looks correct in isolation; the seam between them is where the wrong shape gets mishandled.

# Why it happens

Type-discrimination logic tends to grow where the input first needs it — usually validation or parsing. Downstream stages (resolution, rendering, dispatch) were written earlier or by someone who only pictured the common shape, so they never ask the question the first stage already answered. The knowledge lives in one place; the decision that needs it lives in another. Nothing forces them to agree.

# The rule

Decide an input's form ONCE, as early as possible, and carry that decision — not just the raw value — through every stage that consumes it.

- Classify the input into an explicit, typed form at the boundary (a tagged value, an enum, a small wrapper), not an ad-hoc check.
- Pass the classified form forward. Every stage that acts on the value branches on the tag it was handed, never re-guesses from the raw string, and never assumes the default shape.
- Treat any stage that resolves, fetches, opens, or renders the value as a consumer that MUST see the tag. If it silently assumes one shape, that is the defect, even when the happy path works.
- If two stages must each know the form, that is a signal to centralize the discrimination and share its result, not to duplicate the check (duplicates drift).

# The test that would have caught it

Coverage that only exercises the common shape proves nothing about the seam. For every distinct form the input can take, write an end-to-end test that drives the WHOLE pipeline with that form and asserts on the final artifact — not just that the boundary validator accepted it. The alternate-shape path is exactly the one no one exercises by hand, so it is the one that must be pinned by a test. A contract that says "this input may be shape A or shape B" is only real when both A and B have a passing end-to-end case.

# Quick self-check

- Does any stage after the first re-inspect the raw input to decide its form? Collapse that to one classification and pass it forward.
- Does a resolve[PATH] step assume the default shape? Give it the tag and make it branch.
- Is every declared input shape covered by an end-to-end test that asserts on the output, not just on admission?
