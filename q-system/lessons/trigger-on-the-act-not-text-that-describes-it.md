---
id: trigger-on-the-act-not-text-that-describes-it
kind: pattern
title: Trigger on the act, not text that describes it
date: 2026-07-20
---

A detector that decides an event happened by matching keywords will also fire on text that merely NAMES the event without performing it. The classic false positive: a build[PATH] entry whose description mentions the tracked action gets counted as the action itself. Worst case, the system self-registers against its own development or self-test activity, so the false record looks like real production traffic.

HOW to avoid it:

1. Bind the trigger to the delivery chokepoint, not to language. If an event is only 'real' when it flows through one specific code path (the function that actually sends[PATH]), key the detector on execution reaching that path — not on a string that could appear anywhere, including a description of the path.

2. Separate 'X was done' from 'a string mentions X.' A commit message, a changelog line, a comment, or a log entry that references the feature is metadata about the work, not an instance of the work. Your matcher must be able to tell them apart. Content-scanning alone cannot; provenance can.

3. Exclude self-referential and development-time sources explicitly. Activity generated while building or testing the feature will contain the feature's own vocabulary. Filter it out by source (dev branch, test harness, build tooling, the feature's own commits) rather than hoping the keyword never appears there.

4. Prefer a structured signal over a substring. Emit an explicit typed marker at the true delivery point (an event record, a flag, a distinct call site) and register on that marker. Substring or language matching against free text is a heuristic that will collect descriptions along with occurrences.

5. When you must scan text, require corroboration. A keyword match should be a candidate, not a confirmation — gate it on a second signal that only a genuine delivery produces (a side effect, an ack, a state change).

The root cause to internalize: a guard that restricts registration to 'real' events is only as strong as its ability to exclude everything that talks ABOUT the event. Design the exclusion up front, and test it by feeding the detector a description of the event and asserting it does NOT fire.
