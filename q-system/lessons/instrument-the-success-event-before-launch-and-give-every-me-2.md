---
id: instrument-the-success-event-before-launch-and-give-every-me-2
kind: pattern
title: Instrument the success event before launch, and give every metric a consumer that demands it
date: 2026-07-20
---

A missing signal throws no error. When a page or feature goes live capturing only the cheap-to-collect metrics (arrivals in, money out), the middle of the funnel — the conversion event that actually says whether the thing worked — can be absent for days with no failing job, no empty dashboard, no alert. Absence of a metric is silent, and a human skimming a dashboard will not notice a number that was never there. The gap stays invisible until something forces the value to exist.

Two HOW rules follow.

1. Instrument the outcome event at launch, not after. Before shipping anything whose whole point is to make an event happen (a signup, a purchase, a click-through, a completion), wire the custom event that records that exact act. Do not rely on generic auto-captured pageview/traffic events to stand in for it — they prove someone arrived, never that they converted. Verify at ship time that the event actually fires, by triggering it once and confirming it lands in the store, not by assuming the SDK 'is on.'

2. Give every metric a machine consumer that demands the value. A metric nobody reads programmatically is a metric nobody will miss when it goes missing. Make some automated step — a report, a routing decision, a gate, a scheduled check — require the number as an input and fail loudly when it is absent or zero. The forcing function that turns a silent gap into a visible one is a consumer that cannot proceed without the value. If the only reader is a human eye passing over a dashboard, the gap will survive because eyes skip over things that are not there; a machine that needs the value cannot.

Diagnostic for finding these gaps proactively: for each thing you shipped, name the single event that would prove it succeeded, then ask who or what reads that event and what breaks if the event count is zero. If the honest answer is 'nothing breaks,' you have an uninstrumented or unconsumed success metric — fix it before you need the number, because the day you need it is the day you discover it was never collected.
