---
id: if-the-alert-already-contains-the-fix-run-the-fix
kind: pattern
title: If the alert already contains the fix, run the fix
date: 2026-08-10
---

## The rule

When an automated process emits a notification that includes the exact command or action a human should take, that notification is a defect in the emitter, not a wording problem. If the process knows the precondition is met, knows the action, and knows the arguments, it has everything required to act. Handing that to a person adds latency and a queue, and removes nothing.

## How to apply it

**1. Audit your alert text for imperatives.** Grep your notification strings for shell commands, API calls, or phrases like "needs a human", "someone should", "run:". Every hit is a candidate. The test: does the message body contain enough information for the recipient to act without investigating? If yes, the emitter could have acted too.

**2. Convert, don't reword.** Replace the notification with the action, then notify only about the outcome. Keep three preconditions in the converted path:

- A safety predicate that returns false unless every condition for the action holds (the same conditions you were checking before deciding to page).
- Idempotence, so a repeated run is a no-op rather than a second effect.
- An audit line recording what was done and on what basis.

**3. Keep the page only where judgment is real.** A notification earns its place when the recipient must supply information the system does not have: an authorization decision, a spend approval, a destructive confirmation, a tradeoff between outcomes. "The system computed the answer but is not allowed to type it" is not judgment.

## The generalization step (the part usually skipped)

When you fix one instance of this, the fix is worth almost nothing unless you sweep for the class.

- Write the class down as a predicate, not as a story about the one case: *any emitter whose message names a human as the actor and supplies the action.*
- Search every emitter in the system against that predicate the same day. Different surfaces with the same shape do not inherit the fix by being nearby; they inherit it by being found and converted.
- Record the sweep result, including surfaces you deliberately left alone and why. Otherwise the next person re-derives the insight from scratch on a third surface.

## Verify the fix is actually reachable

A converted path that nothing calls is worse than the original page, because the alert stops firing and the work silently stops happening. Before closing:

- Search the whole tree for callers of the new component. If the only references are its own tests and its own documentation, it is not wired.
- Trust call-graph evidence over header comments and docs claiming who invokes it. Comments describe intent at write time; they are not a binding.
- Prove it end to end at least once: trigger the real precondition and observe the action happen without a human in the loop. Reading the code is not the proof.

## Signals you have this problem

- The same alert line repeats across days or cycles with identical content.
- Recipients respond by copy-pasting a command straight out of the alert.
- A component exists whose stated purpose is to automate a class of alerts, but those alerts are still arriving.
