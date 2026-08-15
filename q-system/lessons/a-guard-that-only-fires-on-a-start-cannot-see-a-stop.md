---
id: a-guard-that-only-fires-on-a-start-cannot-see-a-stop
kind: pattern
title: A guard that only fires when something starts cannot see it stop
date: 2026-08-11
---

Guards are written in the direction of the fear that motivated them. The fear is almost always that something unwanted will HAPPEN: an undeclared writer appears, a disabled node is switched back on, a permission is granted, a job is added. So the condition is written as "X became true", and the opposite case, "the thing that was supposed to keep happening stopped", is not a violation at all. It is the guard's resting state. Nothing ever reports it, and the longer it lasts the more settled it looks.

Observed 2026-08-11 on a client engagement. Four nodes feeding a client's sheet were deliberately disabled, correctly recorded in a manifest, and pinned by a check that FAILED if any was re-enabled. The reason written beside the pin was time-boxed: "before the shadow week". The pin was not. The week began, the week ended, nothing computed the end, and the feed stayed off. The client's own operations person reported the silence four days later. Throughout, the writer guard returned exit 0, the workflow watchdog saw a job running every fifteen minutes and reported healthy, and 337 tests passed. Every one of them watched for a write that should not happen; none watched for a write that stopped.

The same asymmetry has a second face: a scheduled job that succeeds while doing nothing. A pipeline branch with no rows to send produces a successful execution indistinguishable from a busy one, so liveness monitoring reports green for the entire outage.

How to apply:

1. For every guard you write, name the opposite failure out loud: what does it look like when the protected thing stops instead of starts? If nothing in the system can report it, that is a second guard to write, not a footnote.
2. A suppression is a decision with a shelf life. Any deliberately-off state carries a reason AND a `review_by` date, and the guard fails on an entry past its date. Enforce it in a test, so an undated suppression cannot be added at all.
3. Measure non-delivery by the AGE OF THE OLDEST UNDELIVERED ITEM, never by a count. A count cannot tell a busy afternoon from a four-day outage; the same 33 items is fine at 10:00 and an incident three days later.
4. Never alarm on silence itself. A quiet day is not an outage and a checker that fires on quiet gets switched off within a week, after which it protects nothing. Fire only when work EXISTS and has not moved.
5. Absence must be louder than a threshold breach. A subject that drops out of the query population reads as "nothing waiting" forever, so check that every declared subject APPEARS in the result before judging any of them, and report the missing one first.
6. When the client or user is the one who notices, the monitoring is the defect. Twice from the same source is a pattern, not bad luck.
