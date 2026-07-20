---
id: enforce-spacing-and-per-channel-floors-in-the-scheduler-not-
kind: pattern
title: Enforce spacing and per-channel floors in the scheduler, not downstream
date: 2026-07-20
---

When a system distributes items across time slots and multiple output channels, make the cadence rules first-class constraints inside the slot-assignment code — not implicit conventions that live only in intent.

HOW:

1. Name the constraints explicitly before assigning any slot: max items per channel per period, minimum spacing between items on the same channel, and a per-channel floor/ceiling for volume. Write them as data the assigner reads, not as prose in a spec.

2. Make the assigner reject or re-spread any layout that violates a constraint. If two items land on the same channel the same day when the rule says one, that is a failed assignment, not an output to publish. Fail closed at assignment time — the downstream publisher will faithfully execute whatever it is handed, so a stacking bug there is invisible.

3. Give every channel its own generation budget and its own source of items. Do not derive one channel's output as a byproduct or echo of another's — that structurally caps the dependent channel at the driver's rate and starves it. If a channel supports a higher native cadence, wire an independent producer that fills to that cadence.

4. Verify against published state, not intended state. Query what actually got scheduled/emitted and count per channel per day; confirm the counts match the declared constraints. An empty or absent downstream id on committed rows is a signal the spread happened before anything real was booked.

5. Add a check that fails when any channel sits below its floor over a window — underuse is as much a defect as overstacking, and only a floor constraint surfaces it.
