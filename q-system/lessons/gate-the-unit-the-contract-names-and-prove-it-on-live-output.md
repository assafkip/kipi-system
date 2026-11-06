---
id: gate-the-unit-the-contract-names-and-prove-it-on-live-output
kind: methodology
title: Gate the unit the contract names, and prove it on live output
date: 2026-10-12
---

When a quality rule is written for "each thing the user receives" but the output ships as a batch (a digest, a report, a multi-row message), the gate silently changes subject: it inspects the container and passes if anything in it satisfies the rule. Four habits keep that from happening.

**1. Bind the check to the unit, not the artifact.**
- Write down what the contract's unit is: one row, one item, one message. If the contract says "each", the check loops.
- A whole-artifact regex or keyword scan over a batch is an any-match, not an each-match. Any single compliant element clears it.
- Add one test whose artifact has one compliant element and one non-compliant element. If that artifact passes, the check is bound to the wrong unit.

**2. Classify items by content, not by structure.**
- Structural inclusion rules (who wrote last, which field is set, whose turn it is) select items that are shaped like work but are not work. A receipt, a notification, an acknowledgement and a closed item all pass a structural filter.
- Give each source item an explicit content classification with its own name and its own tests. "It appeared in the feed" is not a classification.

**3. A single observation is not a fix.**
- Seeing a bad item absent from one rendering proves it was absent from that rendering. Ranking, volume or timing can hide an item that nothing removed, and it returns on a quieter day.
- Before recording any item as resolved, name the rule or test that now makes its presence impossible. If there is none, record it as "not seen once", not as fixed.

**4. Every exemption gets a leak test, not just a happy-path test.**
- Reviews that fight false positives tend to produce exemptions: this content type skips the rule, that container skips the gate, this category skips the requirement. Each exemption arrives with a test proving the exemption works.
- The untested half is what the exemption now lets through. For each one, add a test that puts genuinely non-compliant content inside the exempt path and asserts it is still caught, or asserts explicitly and deliberately that it is not.

**5. Done is measured where the contract is measured.**
- If the acceptance criterion is about what reaches the recipient, merged plus green tests is not done. The first real production cycle has to run and be read.
- Author-written fixtures encode the author's model of the rule, so they agree with the rule by construction. At least one test feeds a captured real output batch through the gate, and one post-deploy check reads the actual delivered surface.
- Capture that real sample before the fix, so there is something to replay against the new code.
