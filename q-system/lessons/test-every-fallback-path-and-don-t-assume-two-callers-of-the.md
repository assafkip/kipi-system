---
id: test-every-fallback-path-and-don-t-assume-two-callers-of-the
kind: methodology
title: Test every fallback path, and don't assume two callers of the same resource behave alike
date: 2026-07-06
---

When a component depends on an external resource that it can reach through more than one path (a primary path plus a fallback for degraded or alternate environments), two failures hide in the gap between those paths.

First: your tests likely cover the primary path's failure modes (timeout, denial, empty result) but not the fallback's. A fallback that is only exercised in rare conditions is the code least likely to have a test and most likely to hang or misbehave when it finally runs. Write a test that forces the fallback path to execute and asserts it makes progress under the same failure modes you already test on the primary path, especially timeout and hang. An untested fallback is a latent hard-halt, not a safety net.

Second: do not assume two ways of reaching the same resource behave identically. Access to a protected resource can differ by who is asking and how the request surfaces. The same read that returns instantly from one caller can block, prompt, or be denied from another, because the resource keys its behavior on caller identity, invocation context, or which prompt surface it can present. The 'they both just read the same thing' assumption is an implicit contract that the environment does not honor.

How to apply: (1) enumerate every distinct path to an external or protected resource, including the ones that only fire in degraded, elevated, or headless conditions. (2) For each path, add a test that drives it directly and bounds its time — a hang must fail as a timeout, not stall the caller. (3) For any path whose behavior could depend on caller identity or prompt surface, treat it as a separate contract with its own timeout and its own failure handling; never let one path inherit the tested guarantees of another. (4) On startup or any blocking dependency, always bound the wait so an untested or newly-diverging path degrades to a clear failure instead of a silent freeze.
