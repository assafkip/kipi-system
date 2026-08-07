---
id: a-check-must-be-able-to-fail-for-the-reason-you-care-abou
kind: pattern
title: A check must be able to fail for the reason you care about, or it is decoration
date: 2026-08-05
---

A test, gate, metric or diagnostic can pass while being structurally incapable of detecting the thing it was written to detect. It then reads as evidence of correctness and is worse than having no check at all, because it retires the question. The defect is not carelessness: checking a proxy for a property is easier than checking the property, and the proxy usually agrees, so nothing feels wrong.

Observed twelve times in a single engineering session, split roughly evenly between the author and the reviewer. A test asserting a permission flag when the property was availability, controlled by a different flag. A table of malformed inputs where a coarse range guard already rejected every row, so the fine-grained parse could be deleted with the suite green. A binding test run against the one fixture shape structurally unable to exercise the binding. A measurement whose number equally supported "this is safe" and "this does nothing", read as the first. A process-matching pattern that could not distinguish the process to kill from the process to protect. A rate metric that by construction reports only on one subset of decisions, read as reporting on all of them. A pipeline whose exit status came from its final formatting command rather than the gate it wrapped, reporting success while the gate was red.

How to apply:

1. Before trusting a green result, name the concrete input that would make it RED for the reason you care about. If you cannot construct that input, the check is decoration. Delete it or rewrite it; do not leave it passing.
2. Mutation-test the GUARD, not only the code it guards. Delete or invert the guard and confirm a test dies. A guard that can be removed with every test still green is not enforcing anything, and this is invisible to ordinary review.
3. For races, timing and anything intermittent, a single run proves nothing in either direction: it can pass on broken code and fail on correct code. Iterate to N red before the fix and N green after, and use elapsed time as independent corroboration that the run actually exercised the path.
4. Distrust the convenient explanation for an intermittent failure. "Contention", "flake", "transient" each cost one measured run to refute. Skipping that run converts a real defect into a false claim about a gate's state, which is worse than a wrong conclusion because it looks settled.
5. Watch for the asymmetry of recomputing someone else's number while waving through your own. Both occurred in one session from the same engineer, who correctly named it afterward.
6. Grade the INPUT before grading the source. A reviewer that read nothing is not weak evidence; it is not evidence at any strength, and its output should be discarded unread rather than triaged.

The general contract: a check earns trust from the failure it can produce, never from the pass it did produce. State the red-making input first, and the pass becomes meaningful.
