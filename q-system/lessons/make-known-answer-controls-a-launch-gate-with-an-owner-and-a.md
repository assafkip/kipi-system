---
id: make-known-answer-controls-a-launch-gate-with-an-owner-and-a
kind: methodology
title: Make known-answer controls a launch gate, with an owner and a plausibility band
date: 2026-10-19
---

Before starting any long-running batch job, run a small pilot that includes inputs whose correct outcome is already known, and require that pilot to pass before the full run launches. Three practices make this work.

1. Make the control a gate, not a reading. A control written as a sentence in a findings document gets looked at whenever someone gets around to it, which can be hours after the job has consumed its budget. Encode it as a precondition in the launch procedure: the known-answer check runs first, takes minutes, and blocks the full run if it fails. Size the pilot by measuring per-item cost and picking a sample that finishes in roughly a minute or two.

2. Ensure the control can actually fail. A control whose expected result was derived from the same data the method already used is true by construction. It confirms nothing about new coverage. Choose known positives independently of the method under test, and where possible add known negatives, so a broken pipeline produces a visible miss.

3. Give every terminal state a machine owner. If a job is expected to outlive the agent or session that launched it, the instructions have implicitly designed a handoff state such as 'partial, checks pending'. Whoever must verify results afterward cannot be a person's or session's memory. Attach the post-run check to the job itself (a completion hook, a scheduled verifier, or a status file that a named consumer polls) so the check runs automatically and its result is recorded.

4. Convert prior rates into plausibility bands. When earlier runs give a baseline rate, do not just record it as background. Define an expected range up front and have the job flag results outside it, so a run that silently produces implausible output is stopped or reviewed early instead of discovered after completion.

Checklist before launching any long pass: Is there a fast pilot with independent known answers? Does failure block launch? Does the post-run check have an automated owner? Are baseline rates expressed as ranges the output is compared against?
