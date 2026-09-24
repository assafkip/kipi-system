---
id: an-env-var-gate-on-a-guard-is-the-callers-to-open
kind: pattern
title: An environment-variable gate on a guard is the caller's to open
date: 2026-09-02
---

Twice in one PRD a "test-only" override was gated on an environment variable: `PYTEST_CURRENT_TEST` for the unscrubbed copy seam, and again for a receipts-file override in the push guard. The caller sets its own environment, so both were a way to bless your own lesson. One got a second condition (the instance must live under a temp root); the other was removed outright, and the guard now names the variable and ignores it. Codex adversarial on issues 7 and 11 of prd-lessons-rail-and-up-rail.

How to apply:

1. A guard must not have an override that the same caller can switch on. If tests need a seam, make the seam depend on something a real run cannot have (a temp-rooted tree), or give tests real fixtures instead.
2. When a variable exists for tests, print that it was seen and ignored; silence is how a spoof goes unnoticed.
3. Mutation-test the gate: remove the second condition and a test must go red.
