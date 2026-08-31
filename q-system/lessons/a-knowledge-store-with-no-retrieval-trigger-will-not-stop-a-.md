---
id: a-knowledge-store-with-no-retrieval-trigger-will-not-stop-a-
kind: methodology
title: A knowledge store with no retrieval trigger will not stop a repeat
date: 2026-08-31
---

## The shape

A team writes up a failure, names it, files the write-up in a dedicated directory, and fixes the local instance. Weeks later the same failure class ships again under a different name, in a different subsystem. The write-up existed the whole time. Nothing read it.

Three conditions produce this, and all three are structural rather than personal:

**1. The prior-art step is scoped to a workflow the task never entered.** The rule that says "read prior context before you build" usually lives inside a planning ritual. Work that arrives as an execution list, a handoff, a ticket with the steps already decided, reads as execution and never enters that ritual. The step is not skipped in defiance of the rule; the rule simply does not apply to the shape the work arrived in.

**2. A good handoff suppresses the instinct to look further.** A thorough, correct, well-written brief is the most effective way to stop someone from going looking for more context. It reads as sufficient. The better the brief, the stronger the suppression. This is worth stating out loud because the usual instinct is to fix repeats by writing better handoffs, which makes it worse.

**3. The knowledge store has no retrieval trigger and is indexed by conclusion.** Compare the layers that actually reach a worker: config that loads automatically, context injected at session start, a check that runs on every write. Then compare the deep write-ups: filed by hand, named for their conclusion, loaded by nobody. Naming a document for its conclusion means it is only findable by someone who already suspects the answer exists. The deepest material ends up the least reachable, and depth is not the compensating factor people assume it is.

## What to build instead

**Index by failure shape, not by conclusion.** A title that states the lesson is retrievable only after you have learned it. A title that states the situation is retrievable before. "A scoped check judged an input it was not written for" is findable while you are writing a scoped check; the punchline version is not.

**Give the store a trigger, not a location.** Pick one: surface candidate entries automatically when a work session opens, or attach the lookup to the artifact class rather than the workflow, so any entry path into that kind of work hits it. A store that is only read on request is read by people who did not need it.

**Make prior-art recon a property of the work, not of the entry path.** If the reason to read history is that you are about to change a certain kind of thing, then the trigger belongs on that thing. Routing it through a planning mode means every non-planning entrance is a silent bypass.

**When the same fix lands a third time, the deliverable is the class, not the fix.** Correct local fixes plus a scar comment each time is exactly what a recurring class looks like from the inside: every occurrence feels handled. Treat a second recurrence as the signal to stop patching instances and start registering the class by name, in a place a check can read. Then make the check refuse the shape rather than the instance.

## The test

Name a specific past incident. Then ask: if that same class arrived tomorrow, through an entry path nobody anticipated, what mechanism puts the write-up in front of the person doing the work? If the honest answer is "they would have to think to search for it," the store is decoration and the repeat is already scheduled.
