---
id: classify-the-fetched-artifact-not-the-success-code
kind: pattern
title: Classify the fetched artifact against the goal, not the fetch's success code
date: 2026-07-10
---

A fetch that "succeeded" -- exit 0, a file written, a page rendered, a non-empty response -- has not necessarily returned what you asked for. When the source is adversarial or gated, the success path routinely yields an anti-answer that passes every mechanical check: a bot-check or CAPTCHA interstitial, a login or paywall page, a soft-200 error page, a blank render, an empty-but-valid result set. The transport worked; the content is the opposite of the goal.

Two traps let this ship silently:

1. **The success code is not the content.** exit 0 / HTTP 200 / "the file exists" proves the machinery ran, not that the payload is the subject. A status the fetcher writes for itself (`COMPLETE`) records that bytes arrived, not that they are the thing you wanted.

2. **A human or model spot-check does not scale, and it generalizes.** Reviewing one sample and extrapolating to the batch is the classic error -- the item you looked at is not the item that walled. A per-item eyeball is also non-deterministic: whether the reviewer looks at all, and how hard, varies run to run.

How to avoid it:

- **Validate content against the goal, per item, deterministically.** Write a function that inspects the actual returned artifact and answers one question: "is this the subject, or a stand-in?" Run it on every item, at fetch time, and record a status distinct from "the transport succeeded" (e.g. `WALLED`, `EMPTY`). The success flag and the content verdict are separate claims that need separate fields.

- **Combine independent signals; calibrate on real samples.** No single signal is sufficient, and a rich artifact and its opposite can each fool one of them. Measure thresholds against captured good-and-bad examples, never guess them. (One durable shape: a rendered page's visual uniformity AND a text-fingerprint of known interstitials -- a real page can have no extractable text, a blank page can carry hidden markup, so either signal alone has a blind spot.)

- **Give the check a two-direction fixture test.** It must flag the known-bad artifacts AND leave the known-good ones untouched. The false-positive direction matters as much as the false-negative: a validator that kills real results is distrusted and then ignored.

- **Enforce the verdict at the point of use, without mutating the record.** The consumer (report builder, loader, importer) refuses a stand-in-flagged item. For artifacts captured before the check existed, classify them on demand at read time rather than rewriting immutable capture records.

- **The check replaces the glance -- and will catch the glance's mistakes.** The first run of a per-item validator over a batch a human "already reviewed" routinely surfaces items the human generalized wrongly. That is the whole point: a deterministic per-item check is strictly better than sample-and-extrapolate, because it neither tires nor assumes.
