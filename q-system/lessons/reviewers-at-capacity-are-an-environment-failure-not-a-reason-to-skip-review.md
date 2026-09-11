---
id: reviewers-at-capacity-are-an-environment-failure-not-a-reason-to-skip-review
kind: pattern
title: A reviewer at capacity is an environmental failure, not a reason to skip the review
date: 2026-09-02
---

Codex returned "model at capacity" twice on the same issue, twice in the session. Retrying once is fine; retrying more is the loop rule 5 forbids. The review ran on a Claude subagent instead and was stamped `claude-review` / `claude-adversarial`, never as Codex. Those passes found the blocker of the day (an absolute path fanning out into every instance). Issues 7 and 9 of prd-lessons-rail-and-up-rail.

How to apply:

1. One retry, then switch reviewer and stamp the source that actually ran.
2. A false provenance stamp is worse than a missing review in a repo whose thesis is receipts.
