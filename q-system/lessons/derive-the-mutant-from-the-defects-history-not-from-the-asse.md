---
id: derive-the-mutant-from-the-defects-history-not-from-the-asse
kind: methodology
title: Derive the mutant from the defect's history, not from the assertion you just wrote
date: 2026-08-06
---

Mutation testing is supposed to answer "can this test actually fail?" It only answers that if the mutant is chosen independently of the test. When the same person writes the assertion and then writes the mutant to check it, the mutant is not independent -- it is sampled from the space of defects that person was already thinking about, which is the space the assertion already covers. The harness then returns a perfect score and the score means nothing.

**This is a different failure from a broken instrument, and it is much harder to see.** A checker that crashes, or that reports success without running anything, announces itself the moment you look at it -- and the standard defences work: validate that the mutant applied on disk, validate that it changed observable behaviour, watch the check go red before trusting it green. None of those defences fire here. The mutant applies cleanly. It changes behaviour. The test genuinely goes red. Every mechanical validation passes. The instrument is in perfect working order and it is pointed at the wrong target, because the person holding it chose the target after choosing the answer.

**The tell is arithmetic, and it is checkable.** A regression test guards a boundary: a length cap, a timeout, a threshold, a retry count, a size limit. If the fixture is smaller than the boundary it guards, the test cannot see the boundary move. A 51-character fixture body cannot detect a 120-character truncation cap; it can detect a 12-character one. Both mutants "truncate the body," both look like the same defect written up, and only one of them is the defect that actually shipped. The written-after-the-fact mutant is reliably the one the fixture can already see, because that is the one that came to mind while looking at a passing assertion.

**The correct source for a mutant is the version-control record, not memory and not the test.** The defect has a real historical form: an exact line that existed before the fix. `git log -S'<fragment>'` on the file finds the commit that removed it, and `git show` gives the literal text. Restoring that literal text is a mutant nobody chose. If the suite stays green against it, the regression test does not guard the regression it names, and that is the finding -- discovered before the claim is made rather than by a reviewer afterwards.

**When there is no history, the mutant still must not come from the assertion.** For a defect that never shipped, derive the mutant from the defect's mechanism as stated in the issue or the bug report, written down BEFORE the test. If the only available source is the assertion you just wrote, say so instead of reporting a kill count: an unsourced mutant produces a number that reads like evidence and is not.

**Convergent review does not catch this either.** Reviewers from one model family share the blind spot that produced it, so agreement between two of them is weak evidence, and a clean re-review is mostly evidence about the reviewer. The defence has to be structural -- the mutant's provenance -- not another opinion.

**How to apply.**

- Before writing any mutant, find the defect's historical form: `git log -S'<the removed fragment>' -- <file>`, then `git show <sha>` for the literal line. Record the sha next to the mutant. A mutant with no cited provenance is not a mutant, it is a restatement of the test.
- Compare the fixture's size against the bound the test guards, as a number, and write the comparison down. Fixture smaller than the bound means the test cannot fail for its stated reason, whatever the harness reports.
- Include a deliberate no-op mutant in every run (reorder a tuple only used with `in`, rename a local). The harness must classify it INVALID rather than SURVIVED. A harness that cannot tell a semantically-equivalent mutant from a weak test cannot be trusted to report either.
- Validate each mutant on all three axes and report them separately: applied on disk, changed observable behaviour against a probe independent of the suite, and killed. "Validated on disk" alone permits a mutant that ran against the wrong function.
- Never publish a mutation score in a commit message in the same pass that wrote the tests. Re-derive the mutants from history first, then claim.
