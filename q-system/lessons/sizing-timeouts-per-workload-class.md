---
id: sizing-timeouts-per-workload-class
kind: pattern
title: Sizing Timeouts Per Workload Class
date: 2026-11-01
---

When a pipeline stage fails intermittently and reports several different error messages, treat the message diversity as a symptom, not as evidence of several bugs. Use this procedure.

1. Collect the per-call telemetry for the failing stage: one row per outbound call with start time, duration, caller identity, success flag, and whether the call hit its deadline. If this does not exist, add it before theorizing; a latency distribution is the cheapest discriminator between a logic defect and a budget defect.

2. Plot successful durations against the configured deadline. If the successes cluster within roughly 70-95% of the budget, the budget is the defect: normal variation pushes a predictable fraction of calls over the line. A healthy budget leaves successes in a tight band far below the limit.

3. Trace each distinct error message backward to the same deadline event. A common anti-pattern: the deadline handler returns an empty or null payload instead of raising, the caller passes the empty value to a parser, and the parser emits a shape complaint ("output must be structured"). Downstream validators and quality gates then emit their own complaints about the missing artifact. Three messages, one cause. Collapse them before assigning work.

4. Find out where the budget came from. The usual origin is reuse: a constant sized for a small, fast unit of work was later shared by a stage producing output one or two orders of magnitude larger. Grep for the constant and list every call site; the mismatch is visible as soon as the output sizes are put side by side. Check repair, retry, and revision paths too, since they are often copies of the original constant and frequently do more work than the first attempt.

5. Fix in two layers. First, make the deadline distinguishable: have the timeout path raise or return a typed failure so no downstream component ever reinterprets emptiness as malformed content. Second, replace the shared constant with per-workload budgets derived from measured p95 or p99 duration plus headroom, not from a round number. Where work size varies continuously, scale the budget from an input-size estimate.

6. Verify with the same telemetry, not with a single passing run. The original defect only fired on a minority of calls, so confirm that the timeout count over a full cycle is zero and that successes now sit well inside the new budget.

7. Keep unrelated defects separate in the write-up. If part of the failure window has a different origin, record it as its own cause with its own fix rather than folding it into the main narrative, so future readers do not credit one fix with resolving both.

Standing guardrails: never let a deadline produce a valid-looking empty result; alert on near-deadline durations rather than only on failures, since a stage running at 90% of budget is already broken and simply has not been unlucky yet; and treat any timeout constant shared by call sites with different output magnitudes as a latent defect during review.
