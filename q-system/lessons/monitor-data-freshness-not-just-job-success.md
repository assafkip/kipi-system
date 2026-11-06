---
id: monitor-data-freshness-not-just-job-success
kind: pattern
title: Monitor Data Freshness, Not Just Job Success
date: 2026-11-03
---

When a scheduled job depends on data arriving from an external source, a successful run tells you only that your code executed — not that anything new arrived. Build health checks around evidence of data movement.

How to apply:

1. Separate the two signals. Emit one indicator for "the run completed without error" and a distinct indicator for "new data was observed." Never let the first one alone drive a green status.

2. Instrument recency directly. On every run, record the timestamp of the newest record or batch actually ingested. Alert on the age of that value (time since last observed change), not on the age of the last run.

3. Set the freshness threshold from measured arrival behavior. Collect a window of historical arrival times, take a high percentile, and add margin. Avoid thresholds derived from the nominal schedule, which assumes punctuality the source never promised.

4. Make the threshold tolerant of legitimate shifts. Arrival times from external parties drift with clock changes, calendar boundaries, holidays, and upstream maintenance windows. If a shift of an hour or a day is plausible and harmless, the alert window must absorb it, or you will train responders to ignore the alert.

5. Normalize time handling at the boundary. Store and compare instants in a single absolute representation; convert to local or wall-clock time only for display. Expect that any schedule expressed in local time can expand, contract, or repeat an interval when offsets change.

6. Distinguish stale from absent. "No new data and the source confirms none exists" is a healthy state; "no new data and we cannot tell why" is not. Where the source exposes a manifest, cursor, or last-modified marker, check it so an idle period is classified correctly instead of paging someone.

7. Scope the extra machinery. Jobs on schedules you fully control, with inputs you produce yourself, usually need only run-success monitoring. Reserve freshness checks for dependencies whose timing you cannot dictate — that keeps the added complexity where it earns its cost.

8. Validate by simulation. Before relying on the check, replay a frozen feed and a delayed-but-recovering feed against it. Confirm the first fires and the second stays quiet.

The habit to carry forward: define "healthy" in terms of the outcome the system exists to produce, and verify that outcome explicitly. A process that ran is not the same as a result that changed.
