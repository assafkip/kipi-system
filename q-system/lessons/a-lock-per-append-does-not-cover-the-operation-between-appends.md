---
id: a-lock-per-append-does-not-cover-the-operation-between-appends
kind: pattern
title: A lock per append does not cover the operation between the appends
date: 2026-09-02
---

The two-phase receipt took a flock inside each append (pending, then done) and released it in between, so two promotions of one destination could interleave around the copy. The fix takes the lock once on an inherited descriptor before the pending row and holds it to exit; on macOS, which ships no flock(1), a child python process locks the fd and the shell keeps it. Both Codex passes on issue 10 of prd-lessons-rail-and-up-rail.

How to apply:

1. Draw the critical section around the whole sequence that must not interleave, not around each write.
2. A lock that lives on an open file description survives the child that took it; use that when the shell has no flock.
3. Prove it with a test that holds the lock from outside and shows the operation blocks before its first write, and a probe that finds the lock still held mid-operation.
