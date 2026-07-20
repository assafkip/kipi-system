---
id: measure-a-feature-s-resource-cost-by-stubbing-the-expensive-
kind: methodology
title: Measure a feature's resource cost by stubbing the expensive call and counting the cheap proxies
date: 2026-07-20
---

When two modes of a system claim different resource footprints (a bounded default vs an unbounded/recursive deep mode), do not verify the claim by running the real, metered workload. Stub the one expensive external dependency — the paid API call, the subprocess, the network round-trip — and count the deterministic proxies that drive that cost instead: how many workers/agents get spawned, and the summed budget ceiling (max iterations, max turns, max retries) across them. Run each mode against a throwaway copy of any stateful store so the experiment leaves no side effects and costs nothing metered.

The method: (1) identify the single dominant cost driver and replace it with a stub that records calls but does no real work; (2) pick countable proxies that are upstream of that cost and move monotonically with it (spawn count, aggregate turn/iteration budget); (3) run each mode once against isolated throwaway state; (4) compare the counts and state a directional verdict. This turns a fuzzy, expensive-to-check claim ('this mode is cheaper') into a cheap, repeatable, deterministic measurement.

Why it holds: the proxies bound the real cost from above, so a reduction in spawns and total budget is sufficient evidence that actual usage cannot have increased — without ever paying for the real run. Keep the stub and the throwaway-copy harness checked in so the comparison can be re-run whenever either mode changes, guarding against silent regressions where a 'bounded' default quietly grows unbounded.
