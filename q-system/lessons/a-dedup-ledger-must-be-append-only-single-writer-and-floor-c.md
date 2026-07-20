---
id: a-dedup-ledger-must-be-append-only-single-writer-and-floor-c
kind: pattern
title: A dedup ledger must be append-only, single-writer, and floor-checked
date: 2026-07-20
---

When a file is the only durable record of "what already happened" (dedup, idempotency, sent-log, seen-set), three failure modes converge to lose history silently. Design against all three from the start.

1. Never rewrite the whole record to add one entry. A read-modify-write of the entire file means any writer starting from a stale in-memory copy, any crash mid-write, or any concurrent rewrite replaces the whole file and drops prior entries with no error. Use an append-only path (one new line/record per event) or, if you must rewrite, write to a temp file and atomically rename over the target so a partial write can never truncate the live copy.

2. Allow exactly one writer, or make all writers share append discipline plus a lock. Two independent processes touching one file with no coordination is a lost-update setup: the second writer's rebuild overwrites the first's entries. If a second component legitimately writes the same data, route both through a single owning writer, or gate every write behind a file lock and an append-only protocol.

3. Give the record an integrity guard so silent loss is caught, not discovered by a human. The record's row count should only grow; a drop is a corruption signal. On each run start, read the count and compare against a persisted floor (or the last known count) and refuse to proceed / raise an alert if it fell. Keep a versioned backup or snapshot so a bad state is recoverable, not terminal.

The anti-pattern to reject: treating a live, per-operation lookup as the safety net for the durable record. A manual or in-flight check catches one case at a time; it is not a data guarantee and it will not notice that the underlying record silently lost history. The record itself must be the guarantee.
