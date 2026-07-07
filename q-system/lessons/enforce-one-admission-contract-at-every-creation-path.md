---
id: enforce-one-admission-contract-at-every-creation-path
kind: pattern
title: Enforce one admission contract at every creation path
date: 2026-07-06
---

When the same class of bad record keeps reappearing after you "fixed" it, the cause is usually not the record — it is that the rule for what counts as a valid record of a given type lives in several places instead of one. Independent creation paths (an extraction step, a consolidation step, a caller that hands you pre-shaped input) each grow their own local validity check, added the day some variant leaked through that specific door. Patching one door leaves the others open, so the same defect gets re-fixed two or three times against different code, once per path.

The HOW:

1. Define a single admission authority — one function (or module) that answers "is this an admissible entity/record of type X?" Its inputs are the raw value and its claimed type; its output is admit or reject, with the reason. This is the only place the rule lives.

2. Route every creation path through that authority before anything is persisted or added to the shared structure. No path may create-and-type on its own. If you find a second copy of the rule, that is the bug — delete it and call the authority.

3. Re-validate value against claimed type at the write boundary — never trust a type label supplied by an upstream producer, especially the highest-volume one. If a value is tagged as type X, confirm the value actually looks like an X (and does not look like a different type). Self-attested types are input to validate, not facts to accept.

4. Enforce at the write, not the read. Cleanup passes that scrub bad records after the fact are a signal the admission gate is missing or bypassed; keep the cleanup as a backstop but treat every record it removes as a leak past the gate to be closed.

5. When the same class recurs, audit the creation paths, not the individual record. Ask "how many places can mint one of these, and do they all call the one authority?" — the answer, not the latest bad record, is the fix.

The test that you did it right: a new admission rule is added in exactly one place and instantly protects every path, and no producer can inject a mistyped record by simply asserting its type.
