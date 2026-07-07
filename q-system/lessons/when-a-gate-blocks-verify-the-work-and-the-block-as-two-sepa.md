---
id: when-a-gate-blocks-verify-the-work-and-the-block-as-two-sepa
kind: methodology
title: When a gate blocks, verify the work and the block as two separate questions
date: 2026-07-06
---

A blocking check that stops a deliverable is not a signal to override — it is two independent questions, and you answer each against evidence before touching anything.

Ask them in order:
1. Was the work itself correct? Read the process's own trace/log and confirm it was grounded and complete, independent of the block.
2. Is the block a true defect or a false positive? Judge the check against the same evidence, not against your desire to ship.

A correct run and a correct block coexist often: the work can be done well and still emit an output the check rightly refuses. When both are true, the fix is the output, not the gate.

The reflex to guard against: softening a strict check into a warning so the deliverable passes. That reflex is almost always wrong when the data needed to satisfy the check already existed upstream. Watch for this specific pattern — a process computes a precise value in its intermediate reasoning (an exact count, a specific figure) but the final artifact restates it as a vague quantifier ("most", "roughly", "a significant number"). The precise value was available and got dropped between reasoning and output. A check that catches that drop is doing its job; weakening it would ship the imprecision every time the exact value happened to be inconvenient to surface.

How to apply:
- On any blocking check, write down both answers explicitly: run-correct? block-correct? Do not collapse them into one verdict.
- Before overriding, grep the process's own intermediate state for the value the check demands. If it's there, the artifact is the bug — carry the precise value into the output.
- Never downgrade a gate to advisory as a way past a single failure. Downgrade only when you can show the check itself is structurally wrong, not when this one artifact is annoying.
- A precise value computed anywhere in a pipeline must survive into the final artifact as that precise value; a vague restatement of a known exact figure is a defect, not a stylistic choice.
