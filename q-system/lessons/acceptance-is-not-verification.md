---
id: acceptance-is-not-verification
kind: methodology
title: Acceptance is not verification
date: 2026-08-10
---

Agreeing that a finding is worth addressing says nothing about whether the finding is true. Two separate decisions get collapsed into one whenever a reviewer marks something as accepted and downstream work then treats the claim as established fact. Keep them separate: record "we will act on this" and "we confirmed this against the source" as two independent states, and let only the second one license a change.

HOW TO APPLY

1. Re-derive every claim from the primary artifact before acting on it. Open the thing being described and read it. Never assert file, data, or system contents from what was said earlier in the conversation; conversational context is a summary, and summaries drift.

2. Re-derive numbers yourself. A quantitative claim that cites several supporting places can still be wrong if every citation is the same rounded or truncated value repeated. Recompute from raw inputs once, independently, before the number is used as evidence.

3. A guard, check, or validator is unverified until it has been run against the exact content it is meant to catch. Writing it and shipping it proves only that it parses. Show it firing on a known-bad input, then show it silent on a known-good one.

4. Apply the strictest scrutiny to claims that match what you or the requester already believe. Motivated reasoning is acceptance-without-verification aimed inward. When a finding is pleasing, that is the signal to go read the source, not the signal to move on.

5. Do not use reviewers you spawned to check work you produced. A reviewer that inherits the author's framing, and a corpus the author selected, will agree at a rate that looks like confirmation and behaves like an echo. Test it: pre-register the specific disagreements a genuinely independent reviewer should surface. If the reviewers score near zero against that list, treat the review as uninformative rather than as a pass.

6. Scale the evidence bar to the blast radius. A broad rewrite justified only by self-review has no verification behind it, regardless of how many review steps it passed through.

SMELL TEST: if you cannot name the artifact you opened and the specific line or value you read, you accepted the claim. You did not verify it.
