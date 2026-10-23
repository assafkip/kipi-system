---
id: a-fail-safe-halt-should-not-fire-where-there-is-nothing-left
kind: pattern
title: A fail-safe halt should not fire where there is nothing left to degrade
date: 2026-09-14
---

## The failure shape

A pipeline checks supporting evidence per claim. When a claim of a given type has been raised and its evidence is missing, the pipeline degrades gracefully. It marks that claim untestable, removes any narration that depended on the missing evidence, and ships the rest of the report with a note.

Then an input arrives that the classifier cannot sort, so no claim is raised at all. The evidence check stays on anyway as a fail-safe, which sounds cautious. The degradation logic, though, only runs when a claim of the right type was raised. In the fail-safe case none was, so the missing-evidence result falls through to the whole-run halt, and the user gets no report.

The input with the least reason to require that evidence ends up with the strictest outcome in the system. Nobody claimed anything the evidence was supposed to support, and still everything is thrown away.

## The reasoning slip behind it

The halt branch usually has an honest comment along the lines of "there is nothing to degrade, so halt the run." The first half of that is correct. The conclusion is the wrong way round. If there is nothing to degrade, shipping the analysis costs nothing, because no claim rests on the missing input. The comment treats "no claim to downgrade" as a reason to discard the analysis when it is really a reason to keep it.

## Why it hides

- The graceful path already exists and has tests, so the team believes missing evidence is handled.
- That path is written a few lines below the halt, but it is only reachable from the branch where a claim was raised.
- Test fixtures almost always contain a classifiable input, so the empty-classification branch is never exercised.

## How to find it

1. List every reason the check can be running. Typical reasons are "a claim asked for it" and "it runs as a fail-safe".
2. Cross each reason with each evidence state: present and read, present but unread, absent.
3. For every cell, write down the outcome the code actually produces. Get it by running the code, not by reading it.
4. A cell that halts the whole run is justified only if shipping in that state would assert something false. A report that is incomplete but labelled as incomplete does not meet that bar.

## The fix shape

- Send the fail-safe miss into the existing degradation path rather than the halt. Attach the coverage marker to the run as a whole, since there is no single claim to attach it to.
- The marker says what was missing and why. It keeps "the input was not supplied" separate from "the input was supplied but not read". Reporting an unread input as absent is a guess presented as a fact.
- Keep the whole-run halt for states where the output would be wrong, not just thin.

## Tests that pin it

- An unclassifiable input with the optional evidence absent. Assert that a report is produced, that it carries a run-level coverage note, and that the note names the absent input.
- The same input with the evidence present but unreadable. Assert that the note says "not read" and does not say "not supplied".
- A regression check that a raised claim with missing evidence still degrades only that claim.
- Watch each of these tests fail against the old branch before trusting that it passes against the new one.
