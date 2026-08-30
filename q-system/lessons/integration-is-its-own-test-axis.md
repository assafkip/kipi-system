---
id: integration-is-its-own-test-axis
kind: pattern
title: Two components can each be correct and still not compose
date: 2026-08-20
---

Unit tests verify a component against a stub of its neighbour. The stub is written from the same understanding that wrote the component, so it agrees. When two real components meet, the seam between them is the one place neither suite looked — and both suites stay green while the pair does nothing.

The instance that named it: a poll loop and an applier, each fully tested, each mutation-verified. The loop claimed a row (compare-and-set, Pending to Processing) and then handed it to the applier, which — correctly, because claim-before-execute is its own rule — claimed it again. The second claim saw `Processing`, returned `skipped`, and **nothing would ever have applied**. Every command the founder typed would have been picked up, marked in progress, and silently dropped.

Neither suite could see it. The loop's tests inject a fake applier that never claims. The applier's tests inject a claim that always succeeds. Each stub encoded the assumption that made its own side correct, and the contradiction lived only in the pair. It surfaced on the first attempt to wire the two to the live API.

The tell is structural, not behavioural: **whenever two components both implement the same safety rule, exactly one of them is wrong.** Claim-before-execute belongs to whoever executes. Two claimers is not defence in depth; it is a deadlock with good intentions.

## The second instance, three days later, in the same lane

The same axis produced a smaller defect that reached the founder. A `production_deps()` factory assembled every real dependency in one place, and one of them called `notion_comment(...)` — a real function, living in a sibling module, that the calling module never imported. NameError on every confirmation.

223 tests were green. Not one of them had ever called `production_deps`. Every test injected its own `comment`, because that is what makes a test hermetic — so the only code path that assembles the real dependencies was the only code path nothing executed. He typed an ambiguous command, the lane correctly computed his candidate list, and the comment carrying it died on the way out. He got a row marked Needs-Clarification, no candidates, and no way to know why.

The generalisation is sharper than the first instance: **a dependency-injection seam moves the untested surface into the factory.** DI makes every consumer testable by construction and, in the same motion, creates one function that no consumer test can reach. The cleaner the injection, the more completely the factory escapes. An undefined name survives review there because the line reads correctly; it is only wrong at the import boundary, which review does not simulate.

The fix that generalises is not another test of the thing that broke. It is a test that enumerates what the factory assembles and fails on any dependency nothing executes — each new one must either be exercised or declared live-only with the reason it cannot be. That converts "we forgot to test the factory" from a judgement into a build failure.

How to apply:

1. Treat the live run as a test axis, not a demo. It is the only run in which both sides of a seam are real. Schedule it before the work is called done, not after.
2. List the responsibilities each component claims. Any responsibility named by two components is a seam defect until one of them gives it up.
3. Write at least one test whose stub does what the real thing does. The loop test that caught the first defect uses a fake applier that claims exactly as the real applier claims — the moment the stub stopped being convenient, the bug appeared.
4. **Find the function that only production calls, and call it.** Every DI codebase has one. Enumerate what it returns and fail on anything unexercised, rather than testing the members you happen to remember.
5. Distrust green suites at a boundary you have never executed. Two mutation-verified components prove two components; they prove nothing about the join.

Related: `the-mode-production-runs-in-is-the-mode-nothing-tests` (the same blindness one layer down — the invocation mode nothing exercises) and `a-value-compared-to-its-own-source-proves-only-self-agreement` (the stub agreeing with the code that wrote it is self-agreement wearing a second file).
