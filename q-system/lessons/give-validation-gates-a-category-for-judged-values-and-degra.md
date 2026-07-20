---
id: give-validation-gates-a-category-for-judged-values-and-degra
kind: methodology
title: Give validation gates a category for judged values, and degrade to caveats not deletion
date: 2026-07-20
---

When a system splits work between deterministic computation and a judgment layer (a model, a human, any step whose value is irreducibly semantic), the validation gate that guards outputs must be designed for BOTH kinds of value. A common failure: the gate is built to stop fabricated numbers, so it only admits values it can re-derive deterministically. Every legitimately judged value then fails validation, and the gate silently rejects the exact output the judgment layer exists to produce. The gate is not broken; it is faithfully enforcing a contract that contradicts the product.

HOW to avoid it:

1. Enumerate the provenance kinds your outputs can have, not just the ones you can verify. If any output is meant to come from judgment, add an explicit kind for it in the schema/enum (e.g. `judged` or `estimated`) alongside the code-traceable kinds. A closed enum that omits the judgment case structurally forbids the judgment output.

2. Verify what is verifiable; ATTEST what is not. For a code-derived value, check the derivation. For a judged value, require it to be declared and carry a caveat (who/what produced it, that it is unverified) rather than proving it. Do not force judged values through a verifier that can only pass computed ones.

3. Make the failure mode SURFACE-WITH-CAVEAT, not reject-to-empty. When a value cannot be verified, the safe output is 'here is the finding; this figure is an estimate, treat as unverified,' not dropping the whole observation. Anti-fabrication is not anti-loss. A gate whose default on doubt is deletion converts every uncertainty into a silent hole in the output.

4. When you tighten a gate to kill one bad case, check the blast radius against the product's normal output. A control added to stop a single fabricated value can reject a whole legitimate class if that class shares the unverifiable shape. Test the gate against real intended outputs, not just the abuse case.

5. If a prior postmortem already named this lesson, verify the fix landed at the source gate, not just in a downstream consumer. A default that drops-to-empty tends to reappear at every new gate until the invariant is enforced where values are first admitted.
