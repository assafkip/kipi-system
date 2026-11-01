---
id: assert-on-captured-output-not-through-a-pipe
kind: pattern
title: Assert on Captured Output, Not Through a Pipe
date: 2026-10-31
---

When a shell test checks that a command produced certain output, capture the output into a variable and match the variable. Do not pipe the command into a matcher. Under strict pipeline failure propagation (the shell option that makes a pipeline fail if any stage fails), a matcher that exits as soon as it finds a hit closes the pipe early; the producing command is then killed by the broken-pipe signal and the pipeline reports failure even though the match succeeded. The race only loses sometimes, so the test passes most runs and fails intermittently, which is why it survives several review passes.

HOW:

1. Rewrite the assertion in two steps: assign the command's output to a variable with command substitution, then match the variable with a shell pattern/case construct or by feeding the variable (not the command) to the matcher. Command substitution waits for the producer to finish, so no stage is killed mid-write.
2. Ground the diagnosis with a one-line measurement before you change anything: under the strict pipeline option, pipe a long generated stream into a matcher that stops at the first hit and print the exit status. Seeing the signal-based status (128 plus the broken-pipe signal number) confirms the mechanism rather than guessing, and documents why the rewrite is the fix.
3. Treat the single occurrence as a class, not an incident. Add a meta-test that scans the registered test bodies and fails if any of them pipes a command into an early-exiting matcher. This is a cheap text-level check and it stops the pattern from being reintroduced by the next contributor.
4. Prove the flake is gone by repetition, not by one green run. Execute the rewritten test on the order of ten consecutive times and require every run to pass before merging; a single pass tells you nothing about a one-in-ten race.

General rule this instance illustrates: intermittent failures in shell tests are usually a strict-mode interaction with process lifecycle (early exit, signals, subshell status) rather than a bug in the thing under test. Prefer assertions whose exit status depends on exactly one process. Any construct where the status is a function of several processes' interleaving is a latent flake, and a repo-wide scan for that construct is worth more than fixing the one you found.
