---
id: classify-a-dependency-s-failures-by-recoverability-not-one-h
kind: pattern
title: Classify a dependency's failures by recoverability, not one handler for all
date: 2026-07-20
---

When your system depends on an external component (a browser/agent bridge, a network peer, a device, an API client), do not model its failures as a single terminal event. Failures of one dependency split into at least two classes: terminal (the dependency is dead, unauthorized, or misconfigured — no amount of local retry helps, escalate to a human) and transient/self-clearing (a stale handle, a lost attachment, a momentary unavailability that a re-attach or reload fixes on its own). Collapsing both into one handler means every recoverable blip triggers the terminal path: work is dropped and a manual-fix alarm fires for a condition that would have cleared by itself.

How to apply:
1. Before writing the error handler, enumerate the ways the dependency can fail and tag each as terminal or recoverable. If you can only name a terminal path, that is the smell — the recoverable class exists whether or not you handle it.
2. Give the recoverable class its own path: attempt a bounded recovery (re-attach, reload, reconnect) with a small retry cap, then fall through to the terminal handler only if recovery fails. Reserve the hard-block-plus-alert for genuinely terminal failures.
3. When you add a self-heal for one specific transient symptom, generalize it to the whole recoverable class in the same change. A retry wired to a single error code or message will not catch the next transient condition that presents differently — you will rediscover the same hard-block under a new surface. Fix the class, not the instance.
4. Encode the classification and the retry cap in code (a runner or handler), not in prose the operator is trusted to remember. A one-off fix that isn't lifted to the error-class level is a latent repeat.
