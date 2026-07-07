---
id: prove-an-optimization-cheaply-then-confirm-it-live-before-yo
kind: methodology
title: Prove an optimization cheaply, then confirm it live before you trust it
date: 2026-07-06
---

When you change a system to make it cheaper or faster, you have two separate questions, and conflating them is the trap. Question one: is the change directionally correct and safe to make the default? Question two: does it actually deliver in production? Answer them with two different gates.

Gate one is a cheap structural harness. Stub out the expensive components so they burn no real resources, run against disposable throwaway state, and measure mechanical, countable quantities — resource acquisitions, spawn counts, time-to-first-result, output volume — against thresholds you write down before you run. Compare the new path head-to-head with the old path in the same harness. Every threshold is an explicit predicate that evaluates to true or false, so the verdict is deterministic and reproducible, not a judgment call. Because nothing real executes, this gate is nearly free and can run on every change.

A passing structural gate authorizes exactly one thing: flipping the default to the new path. It does NOT authorize trusting the new path in production. The stub that made the measurement cheap is also what makes it partial — it proves the resource accounting improved, not that the real, un-stubbed system produces correct results at the new setting.

So gate two is a live end-to-end run with nothing stubbed. It confirms the real system, doing real work, reproduces the win and stays correct. Only after gate two passes does the new path earn production trust.

How to apply: (1) List the mechanical metrics that would move if the optimization worked, and set each threshold as a written predicate before measuring. (2) Build the harness to stub the costly parts and use disposable state, so the measurement is free and repeatable. (3) Treat a structural PASS as permission to change a reversible default, never as production sign-off. (4) Keep a live end-to-end confirmation as a distinct, required step before trusting the change under real load. Naming the two gates separately stops a cheap proxy result from silently standing in for the expensive proof you still owe.
