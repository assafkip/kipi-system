---
id: an-unresolved-instruction-collision-is-a-defect-not-a-judgme
kind: pattern
title: An unresolved instruction collision is a defect, not a judgment call
date: 2026-08-24
---

When two active instructions apply to the same action and point different ways, the failure mode is not picking the wrong one. It is picking either one silently. The collision is information the requester needed and never got.

**The shape**

One layer says all output of a given kind goes through a specific path. Another layer, loaded from a different scope (session config, environment flag, a caller's override), forbids the mechanism that path uses. Both are live. One gets applied, the other is dropped without a trace, and the output ships looking normal.

Repeating the resolution rule in more places does not fix it. A rule that is loaded, read, and restated while the same failure recurs is a description of an intention, not an enforcement mechanism.

**Two things to build**

1. Make the collision detectable at the point of decision. Instruction sets that can conflict need a machine-readable precedence declaration or an explicit conflict list, checked before the action. If the resolution lives only in prose that some executor is expected to recall, it will be resolved silently again.

2. Make the sanctioned path reachable by intent, not by name. A gated lane that runs only when someone invokes its exact identifier is bypassed by any equivalent plain request. Route on what is being produced (output type, destination, artifact class), not on which entry point was typed. Then put the gate on the artifact: the check runs on the thing produced, so both entry paths hit it.

**The test**

A gate that only fires when the caller opts in is not a gate. Name the input where the collision exists and the wrong branch is taken, and confirm the system reports it rather than proceeding. If nothing observes the difference between the sanctioned path and the bypass, the contract is held by memory, which is the same class of enforcement that just failed.

**Recurrence signal**

An action item that has been written down more than once and is still open is evidence the fix belongs in a different layer. The second occurrence is the signal to stop rewriting the instruction and start writing the check.
