---
id: verify-a-guard-s-behavior-by-running-it-before-you-record-th
kind: methodology
title: Verify a guard's behavior by running it before you record the claim
date: 2026-10-05
---

Pattern: never write a claim about what a guard, gate, or validator blocks into durable prose (notes, handoffs, memory) until you have run that guard against an input whose outcome you already know.

Why it fails: forming a belief about how an executable behaves and persisting it takes no step in between. Notes and handoff files are unguarded prose. A later reader or session treats the claim as fact and builds on it, and the error compounds for days.

What to do:
- Before recording a behavioral claim, run the guard on one input that should be blocked and one that should pass. Paste the command and the result next to the claim.
- If you cannot run it, mark the claim as unverified in the text itself.
- Put every durable-prose location under the same provenance check. A lint that covers one handoff file but not the sibling handoff directory or the memory store leaves the exact files that carried the defect outside the gate built to catch it. List the scan roots and compare them to where claims actually get written.

Second failure in the same family: a guard built from two halves that must agree. Example: a command-level deny function covers one set of tools, while a separate deny list covers another set. Nothing asserts the two sets match, so they drift.
- Write a test that compares the two sets and fails when they diverge.
- Give every new guard, harness, or gate a red-first case: one input it must reject. If it cannot be made to fail, it is decoration.
- Self-test a guard that reads live traffic against a captured real transcript, not only synthetic fixtures.

Check: for each guard you own, name the test that fails when it stops blocking. If you cannot name one, the guard is unproven.
