---
id: a-spurious-404-is-not-proof-a-resource-is-gone
kind: pattern
title: A spurious 404 is not proof a resource is gone; verify before you act on absence
date: 2026-07-14
---

Web surfaces return "not found" for reasons that have nothing to do with the resource being gone: rate-limiting, a partial or bot-flagged page load, a logged-out or degraded session, an A/B gate, transient edge errors. An automation that treats a single 404 (or any single "absent" signal) as ground truth will take a permanent action on a temporary condition: skip a real contact forever, mark a live account dead, delete a record that still exists, or message the wrong entity because it acted on a half-loaded page. The absence signal is noisy, and the action taken on it is often irreversible. That asymmetry is the trap.

How to build it safely:

1. Treat a single "not found" as unconfirmed, not final. Retry the load a small number of times with a short wait between (the condition is often transient and clears on reload). Only after it persists across retries do you treat absence as real, and even then prefer a REVERSIBLE action (defer to the next run, flag for review) over a permanent one (mark dead, delete, skip forever).

2. Positively verify identity before any consequential action, do not infer it from a successful load. A page that returns 200 can still be an empty shell, a placeholder, a mismatch, or the wrong entity. Before you message, mutate, or record against it, confirm the concrete markers that prove it is the real, intended target (a real name/identity, expected attributes, a match to what you were looking for). Acting on "it loaded" instead of "it is the right thing, verified" is how automations hit the wrong target.

3. Make the failure defer, not decide. When absence or identity cannot be confirmed this run, the correct outcome is "come back to it," logged with the reason, not a terminal disposition. A terminal decision made on an unconfirmed signal cannot be undone next run; a deferral can.

The durable rule: absence signals from web surfaces are noisy and the actions taken on them are often permanent. Retry a "not found" before believing it, positively verify identity before acting on a load, and prefer a reversible deferral over an irreversible decision whenever the signal is unconfirmed.
