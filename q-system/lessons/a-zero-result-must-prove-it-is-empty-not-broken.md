---
id: a-zero-result-must-prove-it-is-empty-not-broken
kind: pattern
title: A zero result must prove it is empty, not broken
date: 2026-07-27
---

A step that produces output can only report that it ran. It cannot report that the output is right. When an upstream stage fails and the run continues anyway, the final delivery stage still succeeds and ships an empty result that looks exactly like a normal quiet day. The consumer has no way to tell a broken run from a genuinely empty one, and the failure can persist for days without anyone noticing.

How to apply:

1. Separate the proxy from the receipt. The proxy is "the step executed." The receipt is "the thing this step exists to produce actually exists." Record success on the receipt. Zero items produced is a receipt of zero, not a success.

2. Make failure travel downstream. A stage that fails sets a run-level status that every later stage reads before acting. Delivery then either refuses to send, or sends with the degraded status inside the payload: which stages failed, what data is missing, why the count is untrustworthy. An error that is logged but consumed by nothing is not error handling.

3. Make empty distinguishable from broken at the point of consumption. Emit two visibly different outputs: "zero items, all stages healthy" and "zero items, N stages failed." The reader should never have to open a log to tell those apart.

4. Keep one registry of every output channel, each with an expected cadence and a maximum tolerable silence. A channel that exists only in the code that writes it is a channel no monitor knows about. Monitoring must be per channel: the system can be busy overall while one specific channel has been dead for a week.

5. Alarm on a streak, not on a single zero. One empty result is ordinary. K consecutive empty results, or a quiet stretch longer than the channel's declared cadence, escalates to a human.

Verification before calling it done: break an upstream dependency on purpose (revoke a credential, point at a dead host), run the pipeline end to end, and inspect only what the consumer receives. If that output is indistinguishable from a healthy quiet run, the work is not finished.
