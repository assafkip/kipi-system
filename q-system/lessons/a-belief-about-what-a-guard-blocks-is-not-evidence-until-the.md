---
id: a-belief-about-what-a-guard-blocks-is-not-evidence-until-the
kind: methodology
title: A belief about what a guard blocks is not evidence until the guard has run
date: 2026-09-21
---

A durable claim about what a guard, gate or harness does gets written down with nothing between forming the belief and saving it. Handoff notes, memory files and runbooks are prose. Nothing checks that a sentence like "the guard blocks X" came from running the guard. The next session trusts that sentence, and when the guard does not actually block X, the team can lose days working from a false premise.

The mechanism:

1. Someone reads a guard's code or docs and forms a belief about its coverage.
2. The belief goes into a durable note in the same words a measurement would use.
3. A later reader cannot tell a claim that was measured from one that was only inferred, so they act on it.
4. A gate built to catch unbacked claims often exists already, but its scan scope covers only some of the places where notes get written. The defect lands in a note outside that scope.

The fix, in order:

1. Before you write down what a guard blocks, run it against two inputs whose answers you already know: one it has to block and one it has to allow. Record the command next to the claim. If you have not run it, mark the claim as unverified.
2. List every location where durable notes get written, including per-project handoff folders and agent memory directories. Make sure the gate for unbacked claims scans all of them. When you add a new note location, extend the gate's scope in the same change.
3. For any guard built from two halves that have to agree, such as a check on parsed arguments plus a denylist on command names, write a test that compares the two sets. The test fails when one half covers something the other half misses.
4. Give every new harness or gate a red-first case: an input that makes it fail, run once before you trust any green result from it.
5. Give any gate that reads live data, such as transcripts or logs, a self-test against a real sample. A synthetic fixture only proves the gate matches your assumptions.

The common thread is that someone built a guard and nothing asserted that it can fail or that its parts agree. Read any green result from that guard as unmeasured.
