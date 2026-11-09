---
id: every-admission-cap-needs-a-coded-exit-path
kind: pattern
title: Every admission cap needs a coded exit path
date: 2026-11-09
---

When you add a work-in-progress limit that stops new work once the count of open items reaches a ceiling, you are making an implicit contract: everything the limit counts will eventually leave the set. If no code enforces that contract, the limit will turn a slow leak into a full stop.

How to apply:

1. Build caps as pairs. A stop (refuse new starts) must ship together with a drain (a mechanism that moves stuck items out: close, merge, reassign, or exclude them). If the drain exists only as a comment, a doc sentence, or a pointer to a future ticket, treat the cap as incomplete. Verify the drain exists by searching the executable code, not the docs, for the action that removes an item. If nothing automated ever performs that action, every exit is manual and the cap will fill.

2. Audit every terminal branch of your retry and escalation limits. Look at the paths where an attempt budget, review budget, rebase budget, or similar counter runs out. If each one ends with 'alert a human and leave the item open', the open set only grows. Local limits like these hide the problem because each looks reasonable alone. The first component that reads the open set as a whole, such as a global ceiling, is where the accumulated leak becomes a hard stop. Before you add a global count, check the history: how many items left the set by hand, and how long the oldest items have been open.

3. Count only what the consumer can move. For each class of item the ceiling counts, name the actor that can advance it. Items created by a different lane, workflow, or owner that the automated consumer cannot pick up, find, rework, or arm for completion should be left out of the count. If they must be counted, give them their own end-of-run exit, such as auto-close, a handoff, or a time-to-live. A run that ends with items still open and no owner leaves permanent capacity debt behind.

4. Make sure warnings reach a live consumer. A predicted failure that is marked nonblocking and filed into a queue is only useful if something drains that queue. Check that the queue's consumer works. If the fix for a broken consumer is itself waiting in the same stuck pipeline, you have a closed loop and nothing will move. Escalate outside that loop or make the warning blocking.

5. Add a guard. Alert, or exclude items, when an item in the counted set has had no eligible mover for N rounds. Track how many items left the set by hand versus by automation. A rising share of manual exits is an early sign that the cap is missing its drain.
