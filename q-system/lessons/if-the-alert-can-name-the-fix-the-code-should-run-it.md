---
id: if-the-alert-can-name-the-fix-the-code-should-run-it
kind: pattern
title: If the alert can name the fix, the code should run it
date: 2026-08-03
---

## The pattern

When an automated process detects a stuck state, computes the exact remedy, and then emits that remedy to a human as a message, the notification is the defect. Every fact needed to act was already in hand at the moment the code chose to delegate. The human adds nothing but latency.

## The test (apply to every notification your system emits)

Read the alert text. If it contains a concrete command, a specific button to press, or a fully-determined next step, ask: what information does the human have that the emitter lacked? Three possible answers:

1. **Nothing.** The emitter should perform the action itself. The notification becomes a receipt of what was done, not a request.
2. **A safety judgment** (is this actually safe to do right now). Then encode the safety check in code and act when it passes; page only on the ambiguous minority.
3. **Authority** (spend money, publish, delete, sign off). Legitimate. Keep paging.

Only case 3 justifies a human in the loop. Cases 1 and 2 are producer defects, not wording problems.

## Why it recurs after you fix it once

This class has a shape, not a location. You will hit it first on one surface, write a small actor that handles that surface, and consider it solved. The same shape then survives untouched on every other surface, because the fix was filed as "fixed the X notification" rather than "notifications that carry their own remedy are defects."

Two steps close it:

- **Name the class in the fix itself.** Put the general statement in the header of whatever you build, so the next reader recognizes the shape rather than the instance.
- **Sweep by shape, not by memory.** Enumerate every notification/alert emitter in the system and run the test above on each. A grep for imperative verbs and command syntax inside alert strings finds most of them.

## The second failure: the fix that nobody calls

An auto-actor written but never wired is worse than no fix, because it reads as closed. It also inflates the appearance of coverage in any inventory that lists capabilities by presence.

Before closing this class of work, prove the caller exists:

- Search for the new component by name across the whole codebase. If the only hits are its own definition and its own test, it is inert.
- Make the caller-existence check part of the acceptance criteria, not a manual habit. A test that asserts the production path invokes the actor is stronger than a test that only asserts the actor works in isolation.
- If your system keeps a manifest of declared capabilities, treat "present but undeclared" or "declared but uncalled" as a failing state, not a warning.

## Acceptance criteria for this kind of work

- [ ] Every alert containing an executable remedy is either converted to an action or documented as authority-gated.
- [ ] The generalized rule is written where the next engineer touching a similar surface will read it.
- [ ] Each new auto-actor has at least one non-test caller, asserted by a test.
- [ ] A measurement exists: count of human-directed pings before and after, so regression is visible.
