---
id: instrument-the-success-event-before-launch-and-give-every-me
kind: pattern
title: Instrument the success event before launch, and give every metric a consumer that demands it
date: 2026-07-13
---

A missing signal produces no error. When a page or feature ships with analytics for traffic but not for its primary success action (signup, purchase, submit), dashboards look healthy while the one number that matters simply does not exist. Humans skimming dashboards will not notice an absent metric; they notice broken ones.

How to apply:

1. Extend the definition of done for any user-facing surface with a call to action: the surface is not done until the success event fires and has been observed once in the analytics backend. Verify by triggering the action yourself and querying for the event, not by confirming the tracking snippet is present in the code.

2. Enumerate the funnel at ship time: entry signal, middle signal (the conversion action), outcome signal (revenue or equivalent). If any stage has no event, that is a launch blocker, not a follow-up.

3. Give every required metric a machine consumer as early as possible: a scheduled job, report, or decision script that reads the value by name and fails loudly when it is null or absent. A blind spot becomes visible the moment an automated process demands the number; it stays invisible as long as only humans skim charts where the number was never plotted.

4. Audit periodically for absence, not just breakage: list the events each live surface should emit, query what it actually emitted over the last N days, and diff. Zero occurrences of an expected event is a defect even when nothing is red.
