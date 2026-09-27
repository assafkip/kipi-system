---
id: a-read-then-reset-in-two-locked-calls-is-still-a-race
kind: pattern
title: A read then a reset in two separately locked calls is still a race
date: 2026-09-02
---

The propagation streak read the previous count with one locked call and reset it with another; a failure landing between them was erased while the log reported the stale number. The reset now returns the value it reset from, inside the one lock. Both Codex passes on issue 1 of prd-lessons-rail-and-up-rail.

How to apply:

1. Any operation whose log line depends on the value it replaced must return that value from the same critical section.
2. Two correct locked operations in sequence are not one atomic operation.
