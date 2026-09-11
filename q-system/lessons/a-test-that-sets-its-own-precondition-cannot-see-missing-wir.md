---
id: a-test-that-sets-its-own-precondition-cannot-see-missing-wir
kind: methodology
title: A test that sets its own precondition cannot see missing wiring
date: 2026-08-17
---

When a component's behavior depends on an environment value, config flag, or setting that something upstream is supposed to supply, a test suite that supplies that value itself measures only the component's logic. It can pass at 100% while nothing in the real system ever sets the value, because no case in the suite is capable of going red for that reason. The suite's shape, not its assertions, is the defect.

How to apply:

1. Split the two claims. "Given the precondition, the behavior is correct" and "the precondition actually arrives at runtime" are separate propositions needing separate checks. Stubbing is correct for the first and disqualifying for the second.

2. For every stubbed precondition, add one test that stubs nothing and instead exercises the real entry point the way production does: launch the actual runner or start the actual process, and assert on the observed value it sees. If that test cannot be written, the delivery mechanism is not testable, which is itself the finding.

3. Mutate to prove the check can fail. Remove the line that is supposed to deliver the precondition and confirm the new test goes red. If it stays green, it is measuring the stub, not the delivery.

4. Treat documentation that describes a deployment step as unverified until a check reads it. A comment or docstring asserting "this value is exported from the startup environment" is a claim about a file that may not exist. Either point a test at the real source, or write the claim as a TODO rather than as settled fact. Prose describing a mechanism is not the mechanism.

5. Generalize the smell: any test that constructs, injects, or configures the exact thing whose delivery is in question is proving an algorithm and skipping the integration. Scan a suite for self-supplied preconditions before trusting its coverage number.
