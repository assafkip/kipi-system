---
id: the-author-of-a-fix-picks-the-oracle-the-fix-already-passes
kind: pattern
title: The author of a fix picks the oracle the fix already passes
date: 2026-08-30
---

Writing the check immediately after the fix feels like the disciplined move, and it is where a specific bias lands hardest. You have just built a mental model in which the defect is one particular thing, and you reach for the assertion that model makes obvious. That assertion is chosen from inside the model, so it agrees with the model whether or not the model is right. The check goes green, the green is reported, and nothing has been tested except your own belief.

This is not "a check must be able to fail" restated. That rule catches a predicate with no reachable false branch. Here the predicate CAN fail, reliably, on inputs nobody will ever supply. It fails for a reason adjacent to the one you care about, so it looks discriminating right up until the defect walks past it.

Six instances in one session, 2026-08-30, all in the same person's own work:

A cache directory was being written into a source tree. The regression test asserted the tree stayed clean under `git status --porcelain`. It passed against the defect, because the tool being invoked writes a `.gitignore` holding `*` into its own cache directory, so git never reports it. The property that actually changed was a filesystem listing, and porcelain was the property the author expected to change.

A deduplication feature was added to stop a payload repeating every turn. The test asserted that two consecutive payloads DIFFER. Two payloads also differ when the code walks an entire corpus three items at a time, which is precisely the failure the dedupe introduced. The assertion with teeth was that no item shown in turn one appears in turn two.

An import guard was added to stop a collection abort. It passed on the author's machine because that machine lacked the first dependency in the list, so the guard fired before anything else could. On a machine with that dependency installed, the next unguarded import aborts collection exactly as before. Green by coincidence of the local environment.

A post-fix failure count was measured by running the suite at directory scope, because that was faster. The floor runs at repository scope, where different conftests load and different fixtures resolve. Twelve failures at the narrow scope, seventy-three at the real one. The number written into the ledger understated the problem eightfold.

A mutation test raised the constant that bounded the behaviour, to prove the bound was load-bearing. The assertion read its threshold from that same constant, so the mutation moved the behaviour and the yardstick together and the case stayed green. Mutating the CHECK that consults the constant, and leaving the constant alone, turned it red immediately.

A test used a fixed session identifier while the code under test persisted per-session state to disk. It passed on the first run of the day and failed on every run after. The fixture carried state between runs, which no docstring claiming hermeticity can fix.

How to apply:

1. Before writing the assertion, name the exact input that makes it RED for the reason you care about. If you cannot name one, you are about to write decoration. Write the red input first and watch it fail, then write the fix.
2. Mutate the CODE, never the constant your assertion reads. A mutation that moves the behaviour and the threshold together proves nothing and feels like proof. If your check imports its own bound from the subject, mutate the branch that consults the bound.
3. Measure at the scope the consumer runs at. A narrower scope is faster and loads a different set of fixtures, plugins and configuration; the number it gives you is a different number, not a cheaper one.
4. Ask what on your machine is making this pass. An absent dependency, an installed package, a warm cache, a file left by an earlier run. Then arrange for that thing to be present, or absent, and run it again.
5. Give every test that touches persistent state a fresh key per invocation. Run the suite twice in a row before believing it. A suite that is green once and red twice was never hermetic.
6. When a reviewer says your check cannot see the defect, that claim is cheap to settle: construct the input, run it, and read the result. It is usually right, and the times it is wrong are worth the two minutes.
