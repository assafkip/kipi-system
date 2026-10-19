---
id: encode-cost-vs-timeout-contracts-in-executable-checks-not-co
kind: pattern
title: Encode cost-vs-timeout contracts in executable checks, not comments
date: 2026-10-19
---

Problem: A feature flag that enriches each unit of work (extra detail, media, related records) multiplies per-unit latency. An external service enforces a hard time ceiling. The relationship between the flag, the measured per-unit duration, and the ceiling was documented only as a prose comment in a module nobody was editing. Months later a different workflow flipped a similar enrichment flag against the same service, picked a timeout near the measured mean, and reproduced the earlier failure: roughly a fifth to half of units timed out, with a different random subset failing each run. The knowledge existed but could not act, because nothing executable tied the flag to the ceiling.

Pattern: Turn the implicit contract into something that runs.

1. Name the contract explicitly: 'enrichment flag X raises per-unit cost by about N times; the platform ceiling is C; therefore X requires a fallback or a smaller batch.'
2. Store measured numbers (min, max, mean, sample size) as named constants beside the code that sets the timeout, and derive the timeout from them rather than hand-picking a value.
3. Add a guard at the point where the flag and timeout are combined. If the flag is on and the configured timeout is within a safety margin of the observed mean or max, or the observed max exceeds the ceiling, fail fast at config or startup time, or force a fallback such as splitting the batch, paging, or disabling the flag.
4. Add a test asserting that timeout minus observed mean leaves headroom of at least a few standard deviations, and that any flag marked expensive has a declared fallback.
5. Route every caller through one shared wrapper so a second workflow cannot bypass the guard. Keep per-flag cost multipliers in one registry.
6. Treat the failure signature as a search key: 'a different subset fails each run, around a fixed fraction' usually means the cutoff sits on the latency distribution, not that the inputs are bad. Put that sentence in the guard's error message.

Checklist when adding a timeout: Where was latency measured? Does the timeout clear the observed max, not the mean? Does the flag state change the distribution? Is the hard ceiling known and enforced in code? Can another caller reach this path without passing through the check?

General rule: a cross-cutting constraint that lives only in a comment will be rediscovered by incident. Put it where the next change must pass through it.
