---
id: verify-a-guard-s-behavior-by-running-it-before-you-record-th
kind: methodology
title: Verify a guard's behavior by running it before you record the claim
date: 2026-10-04
---

Before writing a belief about what a guard, hook, or validator blocks into any durable place (a memory file, a handoff note, a runbook), run that guard once against an input whose correct outcome you already know. Record the command and its observed result alongside the claim. If you did not run it, mark the claim unverified in the text itself.

Two structural gaps let unverified claims persist:

1. Provenance gates have a narrow scan root. A lint that blocks measurement-shaped statements lacking a command, an evidence id, or an unverified marker only protects the files it scans. Notes written to sibling directories, per-project handoffs, or an assistant's auto-memory store sit outside it, and those are exactly where unchecked beliefs get saved. When you add a provenance gate, enumerate every place durable prose gets written and either extend the scan root or document why a location is exempt.

2. Guards and their sibling lists drift apart because nothing asserts that they agree. When one function denies certain commands and a separate constant lists other denied commands, write a test that compares the two sets. When you build a harness or gate, add a case that is known to fail and confirm the harness reports failure (a red-first case). When a gate reads a live transcript or log, give it a self-test against a real sample, so you know it can fail.

Checklist:
- Run the guard against a known-block input and a known-pass input before asserting what it does.
- Persist the command and the result, not just the conclusion.
- Scan every location that stores durable prose, not only the primary one.
- Add a test asserting that parallel deny lists, allow lists, or rule sets stay in sync.
- Give every gate a case that must fail, so a gate that cannot fail is caught.
