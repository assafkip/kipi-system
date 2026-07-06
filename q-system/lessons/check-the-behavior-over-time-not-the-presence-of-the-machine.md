---
id: check-the-behavior-over-time-not-the-presence-of-the-machine
kind: pattern
title: Check the behavior over time, not the presence of the machinery that could produce it
date: 2026-07-06
---

When a requirement is about how something behaves across time or what role a component plays — a subject that changes state, a value that updates, a process that progresses — presence checks lie. A verifier that confirms the right libraries are loaded, the right fields exist, or a single snapshot looks correct will pass a build where the required behavior never actually happens. The machinery being present is not the behavior being delivered.

HOW:

1. Turn the real requirement into a machine-checkable field, not prose intent. If the requirement is 'the subject changes state over time,' the contract stores and enforces that as a checkable property, not a human-language note that a reviewer is trusted to honor. Intent that lives only in words is not enforced.

2. Test the dynamic property dynamically. Comparing one frame, one state, or one first-render cannot distinguish 'static but present' from 'actually changing.' Sample at least two points across the axis that matters (time, state, progression) and assert they differ in the required way.

3. Verify role fidelity, not component presence. That a capability, library, or dependency is wired in says nothing about whether it drives the thing it was supposed to drive. Assert the effect on the target, not the existence of the tool that could produce it.

4. Watch for the satisficing stop. Proving a new pipeline works end-to-end creates a tempting exit: once the plumbing is clean, the build halts at 'has the ingredients' instead of 'produces the required outcome.' Define done as the outcome behaving like the reference, and keep the outcome check separate from the pipeline-health check so a green pipeline cannot stand in for a met requirement.
