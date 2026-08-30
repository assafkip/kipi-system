---
id: a-guard-the-compound-condition-never-reaches-is-not-a-guar
kind: pattern
title: A guard the compound condition never reaches is not a guard
date: 2026-08-06
---

The guard is written, it is correct, and it never runs. Not because it was deleted or misplaced, but because the branch it lives in is entered through a compound condition, and one of the other clauses is False in exactly the situation the guard exists for. Reviewers read the guard, confirm the logic inside it, and move on. The bug is not in the guard. It is in the reachability of the guard, which is a different question and one that reading the guard cannot answer.

This has now happened three times in one file's history, which is what makes it a class rather than a bug:

1. A pause ledger was read to decide "this job is dark on purpose, do not page". The read sat nested inside the `not_loaded` arm. A job that was paused-and-healthy hit no arm at all, so the ledger was consulted only for jobs already failing. The signal was a one-way silencer, never a detector.
2. A run function returned early when its problem list was empty. The one state the new check existed to judge was exactly the state that produced an empty list, so the check was wired after the return that made it unreachable.
3. An orphan branch was guarded by `not installed and label not in overrides`. A retired job whose stale override row survived satisfied the first clause and failed the second, so it fell past the orphan branch into the drift branch and paged about a job with no executable on disk. Its sibling, retired identically but with no leftover row, classified correctly. The two inputs differed by one clause.

Notice what all three share: the guard is a **signal read on only one side of a branch**. The information is available, the code that uses it is right, and the control flow routes the interesting case around it. Notice also the harm is always the same two shapes, and both are bad: a real condition goes undetected (1 and 2), or a benign condition gets reported as the alarming one (3). Both read as the system working.

HOW to build against it:

1. **Ask what makes the branch fire, not what it does.** For every `and` in a branch condition, name an input where that clause alone is False. If you cannot name one, the clause is either dead or load-bearing in a way you have not understood. In case 3 the clause `label not in overrides` was False for two of the five real orphans on the machine, which was discoverable in one read-only command.

2. **Decide which single fact settles the classification, and let it settle alone.** "No plist on disk" settles that a job cannot be running; an override row is a statement about a different database. When a second signal is genuinely relevant, it belongs in the DETAIL of the finding, not in the CONDITION that selects the finding. Mixing an informational signal into a classifying condition is how this class gets created.

3. **Test with two inputs that differ by exactly the extra clause.** The reproducer that caught case 3 put both retired siblings in one call: same intent, same absence from disk, differing only by the stale row. One classified right and one classified wrong in the same output line, which makes the clause the only possible explanation. A single-input test would have shown a wrong answer without showing why.

4. **Derive the mutants from the branch's own history, then check the population.** Transplanting case 1's shape into case 3's code produced a mutant that SURVIVED the first suite: it only altered behaviour when intent and reality AGREE, and the tests happened to cover only disagreement. Measuring the real population showed 3 of 5 orphans were in that untested majority. The mutation did not just grade the test, it named the missing case.

5. **Prefer the early, unconditional exit.** `if not installed: classify and continue` cannot develop this defect, because there is no second clause to be False. Every additional term in a classifying condition is a future instance of this lesson.

The general form: reading a guard tells you what it does when it runs. It tells you nothing about whether it runs. Those are separate proofs and the second one is the one people skip.
