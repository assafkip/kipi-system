---
id: scoping-guards-to-the-hazardous-operation
kind: pattern
title: Scoping Guards to the Hazardous Operation
date: 2026-10-31
---

When you add a safety check that refuses to proceed under suspicious conditions, scope the refusal to the operation that is actually dangerous, not to the context in which it was discovered.

HOW TO PLACE THE GUARD
1. Write down the hazard as a verb phrase: what concrete action, if taken in this state, causes damage? Usually it is a mutation (write, append, publish, delete), not an inspection.
2. Enumerate every caller that passes through the chokepoint you are about to harden. Split them into those that perform the hazardous verb and those that only read, report, or validate.
3. If both groups pass through the same function, the guard does not belong at that function's entry. Either push it down to the mutating path, or carry an explicit parameter that distinguishes refuse-mode from degrade-mode.
4. Before inventing that parameter, read the function you are wrapping. Resolution and validation helpers often already expose a strictness or tolerance flag, and their documentation may already describe the exact split you need. A new guard layered above an existing axis duplicates and contradicts it; the same decision then lives in two places.
5. State the chosen contract in one sentence next to the guard: "readers degrade, writers refuse." If you cannot write that sentence, the guard is scoped to a symptom rather than a hazard.

FAILURE SIGNATURE TO WATCH FOR
A fail-closed check at a shared chokepoint turns a healthy system into an unreadable one: health checks, status reporters, and pre-flight validators are the heaviest users of resolution helpers, so they are the first things a caller-scoped guard breaks. The symptom looks like data corruption or missing state, but the data is fine and the reader was simply denied.

APPLYING BLAST-RADIUS MEASUREMENT CONSISTENTLY
6. Classify the change before testing it. A change to how a path, identifier, or resource is resolved is a different class from a change to business logic: its effects surface in unrelated suites, because resolution is a shared dependency.
7. Once you have decided that a class of change requires a broad test run, apply that rule to every change in the class within the session. Measuring one resolver edit, getting a scary number, reverting it, and then shipping a sibling edit on the strength of its own narrow suite is worse than never measuring at all, because the green narrow suite now reads as evidence of safety that was never gathered.
8. Treat a passing targeted suite as evidence about the targeted behavior only. For shared-dependency changes, record the collateral count explicitly, even if it is zero, so the number exists as a decision input rather than an assumption.

MAKING THE PRE-PUSH GATE ACTUALLY RUN
9. Identify the single command that reproduces the full validation your pipeline runs, and run that command, not a subset of it. If the pipeline enumerates a fixed set of checks, the local equivalent must enumerate the same set.
10. Never let a long verification run be the thing you launch and walk away from. Backgrounded processes started from short-lived tool invocations or ephemeral shells can be killed with their parent and leave no output and no error.
11. Make the absence of a result an explicit failure. After launching any long check, verify three things before trusting it: the process still exists or exited, an output artifact was produced, and that artifact contains a terminal verdict. A check that produced nothing must be treated as a failed check, not an unfinished one.
12. Prefer running the gate in the foreground and waiting, or write results to a durable artifact whose presence you assert. Silence is the most dangerous test outcome, because it is indistinguishable from success in memory and from failure in reality.

REVIEW CHECKLIST FOR ANY NEW REFUSAL
- Does it refuse a verb or a situation?
- Which read-only callers now refuse, and is that intended?
- Does an existing strictness flag already encode this distinction?
- Was the broad suite run, and what was the collateral number?
- Did the full gate actually emit a verdict, or did I only start it?
