---
id: an-empty-result-must-say-what-it-was-empty-of
kind: pattern
title: An empty result must say what it was empty of
date: 2026-09-07
---

When a stage can legitimately produce nothing, its "nothing" is usually byte-identical whether the input was genuinely empty or whether an earlier stage destroyed the input. Every health surface then reads green: the process exits zero, the heartbeat fires, the report says nothing to report. Nobody can tell a quiet day from a data loss, because there is no observable difference to see.

Fix it at the artifact, not at the monitoring. Make the empty case carry its own provenance: how many items entered the stage, how many survived each filter, and which stage produced the zero. An empty result stamped with an input count of zero and one stamped with an input count of forty are then different bytes, and both a human and an alert can distinguish them.

Two habits keep the class from recurring.

Derive a guard's population from the system, not from memory. If an interlock is meant to stop unauthorized writers to some shared state, enumerate the writers by scanning for the write operation itself, then assert that every one of them is covered. A hand-listed set of protected call sites drifts the moment a new writer appears, and an audit written from the same memory repeats the same omission rather than catching it.

Test order and data flow by executing, not by reading. Checks that assert a line exists in a script, or that a schedule references the right entry point, are blind to which stage reads state before another stage overwrites it. Ordering defects need a run over a fixture with a known input and an asserted output, and the test earns trust only after you have watched it go red.
