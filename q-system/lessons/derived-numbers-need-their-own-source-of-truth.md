---
id: derived-numbers-need-their-own-source-of-truth
kind: methodology
title: Derived numbers need their own source of truth
date: 2026-09-07
---

A finished document can pass every gate and still carry wrong numbers, because the usual controls cover the wrong half of the problem.

**Two failure shapes to design against.**

1. Chain-of-custody for raw inputs is not verification of derived claims. Capturing a tamper-evident copy of an external source answers "do we have a faithful record of what we read." It never answers "does this computed figure in the writeup match the current state of the analysis." A document's totals, counts, percentages and quoted spans are derived artifacts; they drift when the analysis is corrected downstream and nothing re-checks them. Keep an append-only ledger of verified facts, one row per claim, each row carrying the claim, its source, the exact command or procedure that produced it, the result, and when it was verified. Then make final review a mechanical trace: every number and every quoted span in the deliverable resolves to a ledger row, or it does not ship.

2. An opt-in guard that stands down when unadopted protects nothing. A checker that treats a missing ledger as "this workflow has not opted in yet" and passes silently gives the same green as a fully verified document. The absence of the mechanism is invisible at exactly the moment it matters. Make non-adoption a loud state, not a quiet pass: either the workflow declares itself out of scope explicitly, or the checker reports "no evidence base found" as a failure. Existence of a capability is not adoption; check for the artifact, not for the tool.

**Two habits that close the loop.**

- When a mechanism already exists somewhere in the system for exactly this class of problem, adoption per workflow is the work. A shared capability nobody wired into a given pipeline is indistinguishable from one that was never built.
- Gates that ran once against the original scope say nothing about the delivered scope. When scope, inputs, or conclusions change after a gate ran, that gate's green result is stale. Bind each gate run to the version it verified, and treat a scope change as invalidating every prior receipt.

**The test for whether this is in place:** pick any number in the finished deliverable at random and ask which stored, dated, reproducible record it came from. If the answer is "it was computed during the work," there is no source of truth, only memory.
