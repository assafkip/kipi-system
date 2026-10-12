---
id: grade-parser-failures-by-severity-instead-of-rejecting-whole
kind: pattern
title: Grade parser failures by severity instead of rejecting whole runs
date: 2026-10-12
---

When code consumes output from a nondeterministic producer such as an LLM, do not make every validation check a whole-run refusal. Treat validation as tiered.

1. Classify each check by what it protects. Ask: if this check is violated, can bad data reach a consumer, a user, or an external system? If yes, it is a safety check and may reject. If the violation is only an unusual shape, such as extra text outside the expected structure, a different count than expected, or reordered fields, it is a shape check.

2. Shape checks should normalize, tolerate, or degrade instead of aborting. Extract the structured payload from surrounding noise, clamp or truncate counts, drop only the offending items, and log a warning. Reserve whole-run failure for violations that make the output unsafe or unusable.

3. Audit each rule for whether it protects anything. If the content a rule guards can never reach the sensitive field, the rule is dead weight with the power to halt everything. Remove it or demote it to a warning. Be suspicious of limits justified only by a comment saying the case cannot happen. A comment is an assertion, not evidence.

4. Validate assumed limits against real data. Any cap or threshold should be checked against realistic production-like inputs, not set by assertion.

5. Test parsers with the shapes the producer actually emits. Build a fixture set from real outputs, including fenced blocks, leading or trailing prose, empty results, oversize results, and partial results. Assert that each is either accepted, repaired, or rejected for a stated safety reason.

6. When the same failure class recurs, look for the shared design cause. An all-or-nothing contract on a nondeterministic producer will keep failing in new ways until strictness is graded by risk.
