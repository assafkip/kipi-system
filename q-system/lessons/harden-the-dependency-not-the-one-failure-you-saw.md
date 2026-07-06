---
id: harden-the-dependency-not-the-one-failure-you-saw
kind: pattern
title: Harden the dependency, not the one failure you saw
date: 2026-07-06
---

When a flaky external dependency breaks, the fix that only addresses the exact error you observed is a mirage. A flaky source has many failure modes: a missing credential, a timeout, a rate-limit, an empty response, a partial response. Repairing the one that fired today leaves every other mode wide open, so the source fails again a different way almost immediately. Scope your fix to the source's reliability, not to the single symptom.

Do three things instead of one:

1. Give the unreliable source a fallback. If a fast, dependency-light path to the same data already exists, route through it or make it the fallback for when the slow path fails. A slow path with no fallback is a single point of failure dressed up as a feature. Before adding resilience machinery, check whether a simpler path is already sitting unused.

2. Right-size the budget. If a step's time or resource budget sits on the edge of what the work needs on a good day, it loses the race on a normal day. A budget that only passes under best-case conditions is a latent failure, not a safeguard.

3. Pair every detector with remediation. Adding a monitor that fires when output is thin or starved makes the rot visible, but visibility is not repair. A detector that only alerts still ships the degraded output. Wire the alert to an action: backfill from the fallback, widen the window, retry against a second source, or block the release. Detection without remediation converts a silent failure into a loud one and changes nothing about what actually ships.

The verification that closes this out is not 'the original error message is gone.' The error changing is expected once you patch one mode. Verify the actual outcome: the artifact is whole, the source produced usable data through at least one path, and the remediation ran when the primary path degraded.
