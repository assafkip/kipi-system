---
id: anchor-classifiers-with-a-verified-positive-control
kind: methodology
title: Anchor Classifiers With a Verified Positive Control
date: 2026-10-31
---

When a task requires labelling items as genuine or not, the first "genuine" label tends to become the implicit reference for every later judgement. If that first label was never independently confirmed, a single early mistake propagates through the whole batch and gains false confidence with each repetition. Guard against this with three habits.

**1. Verify both poles before classifying at scale.**
- Build a small labelled set that contains known-negative *and* known-positive examples, confirmed by a method independent of the one under test.
- Run the checking procedure against that set and record how many of each class it gets right. Rejecting known fakes proves only that the procedure has some specificity; it says nothing about whether it can recognise a true positive.
- Treat a procedure with zero confirmed positives as unvalidated, and do not let its output leave the sandbox.

**2. Check that your observable actually separates the classes.**
- Write down the property the requester cares about, then write down the signal you are actually able to observe. If they differ, the gap is an assumption that needs testing.
- Ask explicitly: can this signal produce different results for the two classes? Construct one example of each class and see. If both classes yield the same observation, the check has no discriminating power regardless of how careful the inspection is.
- Watch for acceptance criteria that silently substitute an easier question. Confirming *which* thing you are looking at is not the same as confirming *that it has the required behaviour*. Phrase criteria as the behaviour to be demonstrated, not the attribute to be matched.
- When a constraint (policy, cost, access, tooling) removes the only means of observing the required property, say so and escalate. The correct response is to renegotiate the constraint or the deliverable, not to substitute a proxy and hope.

**3. Make the pipeline enforce the check, not just the plan.**
- Do not let a free-text verdict field be the only gate. Downstream assembly code should require the specific evidence that justifies the verdict: the measurement, the artefact, the tool output.
- Have the final packaging step reject records whose evidence field is missing or whose provenance is a weaker method than the one specified. A label is a claim; the pipeline should demand the receipt.
- Record, per item, which method produced the verdict. Uniform provenance across a whole batch is a signal worth reviewing, as is a batch where every item passes.

**Review trigger:** before shipping a batch of classifications, stop and answer two questions in writing — "which confirmed positive example validated this method?" and "what observation would have forced a negative verdict?" If either answer is empty, the batch is not ready.
