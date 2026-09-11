---
id: the-loudest-broken-thing-is-not-always-the-cause
kind: methodology
title: The loudest broken thing is not always the cause
date: 2026-08-11
---

A bad artifact shipped. Investigating it turned up a safety check that had been silently disabled by a dependency sync two days earlier, and which had logged its own outage twenty-two times during the run that produced the artifact. The whole causal story assembled itself in minutes: the check went down, the bad thing got through. It was wrong. Restoring the check and re-running it against the artifact showed it did not catch it and could not have; the two facts were contemporaneous and unrelated. The real cause was a different mechanism that no check was watching at all.

How to apply:

1. Before building a chain from a broken component to a bad outcome, run the repaired component against the actual artifact. If it does not flag it, you have found a second defect, not the cause of the first, and both deserve reporting as what they are.

2. Treat a loud, timestamped, well-logged failure as a suspect with an alibi to check, not as a confession. Its visibility is a property of its instrumentation, and instrumented failures are exactly the ones already being handled. The cause is more often in the part nobody instrumented, which is why it produced a surprise.

3. Ask what the mechanism could see, not just whether it was working. A check comparing text to text cannot catch a semantic reproduction; a check reading structure cannot catch a false claim. When the failed artifact is a kind the mechanism is structurally blind to, its outage is irrelevant to that artifact however dramatic it looks.

4. Beware coincidence in a system that changes daily. In a codebase with many small commits, any given day offers several genuine, unrelated breakages to build a story from, and the first one you find will fit if you let it.

5. Say plainly that the fix does not fix the incident, when that is true. A repair that is correct on its own merits and irrelevant to the reported problem is worth shipping and worth labelling, and conflating the two lets the real cause stay open behind a closed ticket.

The trap is not carelessness. It is that the false chain explains everything, arrives early, and comes with logs.
