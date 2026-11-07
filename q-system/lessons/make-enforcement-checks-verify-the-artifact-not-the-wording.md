---
id: make-enforcement-checks-verify-the-artifact-not-the-wording
kind: methodology
title: Make Enforcement Checks Verify the Artifact, Not the Wording
date: 2026-11-07
---

PROBLEM SHAPE
A system is set up to require that rules be enforced by executable checks rather than written guidance. Yet rules keep landing as prose. Two independent causes combine: the automated gates validate wording instead of validating an executable, and the cost of writing prose is a fraction of the cost of shipping code.

HOW TO FIX CAUSE 1: BIND THE CHECK TO THE PROPERTY
When a gate exists to confirm "this rule is enforced by something that runs," do not let it pass on the presence of a keyword near the claim. A keyword gate is worse than no gate: it teaches authors to type the magic word beside a prose rule, after which the rule reads as enforced and nobody re-examines it.

Steps:
1. Require the claim to name a concrete target in a machine-parseable form (a path, an identifier, a check name) rather than free text. Reject claims that only gesture at a category.
2. Resolve the named target. Confirm it exists at the named location, in the repository state being validated, not only in the file under inspection.
3. Confirm the target is wired: it appears in the registry, config, pipeline definition, or scheduler that actually invokes it. Existence without registration is still prose.
4. Confirm the target can fail. Run it against a known-bad input in a fixture and assert a non-zero or failing result. A check that cannot fail is indistinguishable from a comment.
5. Make each step's failure message state which of the four properties was missing, so the author learns the gap instead of guessing at wording.

Generalize the rule: for any validator, write down the property you care about, then ask what the validator literally inspects. If the two differ, you have bound to the nearest proxy. Common proxies to distrust: a keyword near a claim, a file's presence without registration, a config key without a consumer, a test file without an assertion, a declared owner without a notification route.

Audit your own gates with the same lens you apply to the code they guard. Meta-tooling is where proxy-binding survives longest, because nothing is gating the gate.

HOW TO FIX CAUSE 2: CLOSE THE COST ASYMMETRY
Behavior follows the cheapest legal path. If recording a rule as text is one edit with no review and automatic pickup by the next session, while enforcing it in code requires a separate working copy, a pull request, slow continuous integration, capped review rounds, a merge restricted to one person, a deploy that merges do not trigger, and a wiring path that is broken in most environments, then prose wins every time regardless of policy.

Measure before redesigning:
1. Write the two paths side by side as ordered steps, with wall-clock cost per step.
2. Mark every step that is a hard serialization point: single approver, manual deploy, long pipeline, unavailable prerequisite.
3. Count how many such points each path has. The ratio is your real policy.

Then act on the ratio:
- Remove or automate the single highest-cost serialization point on the enforcement path first; one bottleneck usually dominates the total.
- Provide a scaffold that generates a runnable, wired, failing-by-default check from a one-line description, so the first ninety percent of the code path costs about what the prose path costs.
- Fix any wiring prerequisite that is missing in most environments before asking anyone to use that mechanism. A mechanism that refuses to install everywhere is not an option, it is a trap that consumes the attempt and then reverts to prose.
- Add equal friction to the cheap path where the cheap path is the wrong one: require the prose edit to carry a resolvable enforcement reference, or mark it as explicitly unenforced with an expiry.
- Shorten the feedback loop so an enforcement attempt can be validated locally in seconds without traversing the full release path.

WHAT TO WATCH AFTERWARD
- Track the age of enforcement requests that entered the code path and have not landed. A long tail there means the asymmetry is still live, not that the request was unimportant.
- Track the count of rules that pass the gate but whose named target does not resolve. This should be zero after the fix; if it is not, the gate is still checking wording somewhere.
- Treat "we have a guard for that" as a claim to verify, not a fact. Ask what the guard inspects and what input makes it fail.
