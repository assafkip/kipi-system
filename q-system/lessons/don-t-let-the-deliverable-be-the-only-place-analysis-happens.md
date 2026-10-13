---
id: don-t-let-the-deliverable-be-the-only-place-analysis-happens
kind: pattern
title: Don't Let the Deliverable Be the Only Place Analysis Happens
date: 2026-10-12
---

When a slow or failing generated artifact (a report, export, or summary) is the only place a computation runs, the artifact is no longer a rendering of a decision. It is the decision. Fixing the latency leaves the underlying design flaw in place: the human reviewer ends up judging after the external-facing document already exists.

How to apply it:
1. Map where each critical computation executes. List every call site of the aggregate or cohort-level check and note whether any internal, reviewer-facing surface calls it. If the only caller is the customer-facing generator, you have found the gap.
2. Give reviewers their own surface for the same computation. Expose the aggregate result in the internal workflow, computed once and reused by the generator, so review precedes publication.
3. Treat the invisibility of a failure as a signal. If a timeout or error persisted for a long time unnoticed, ask who depends on that path to do their job. If nobody does, the path is not part of the real workflow, and that is the design bug.
4. Check for placeholders and missing inputs. A stubbed step with a comment explaining that some inputs do not yet exist (a field-name mismatch between code and storage, or a metric that no collection holds) is a common reason the computation migrates into the wrong place. Track those data gaps as blockers.
5. Bound iterative or looped work in time as well as cost. A budget expressed only in money or tokens can still exceed a request's wall-clock limit. Add an explicit per-run time or iteration ceiling, with partial-result or async fallback.
6. Verify audit findings against the code before acting on them. Static reachability tools can flag code as dead when it is called through an aliased or module-qualified import. When documentation and an audit disagree, resolve it by reading the actual call path, then record the outcome.

Outcome: analysis happens before the deliverable, reviewers see what customers will see, and latency limits are designed for rather than discovered.
