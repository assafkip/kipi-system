---
id: an-unattended-session-freezes-on-its-first-permission-prompt
kind: pattern
title: An unattended agent session freezes on its first permission prompt
date: 2026-07-14
---

An always-on interactive agent session started to run a loop autonomously (relaunched by a supervisor, seeded with a task prompt) will stall on the FIRST tool-permission prompt it hits, because no human is present to answer it. The process stays up, the supervisor reports it alive, and its infrastructure (the session, any browser bridge) all look healthy, but the loop never runs a single cycle and its liveness signal goes stale. The failure is invisible from the outside. "The session is running" and "the session is doing its job" are different claims, and a permission prompt silently breaks the second while leaving the first true.

How to build it safely:

1. An unattended session must not be able to block on a human prompt. Launch it with permissions pre-granted (skip the interactive approval), because there is no one to click. The whole premise of an unattended session is that no human is in the loop; a per-command approval gate contradicts that by construction and guarantees a silent freeze.

2. Move the safety from the prompt to the code. Once a session runs without per-command approval, the guardrails that matter are the coded ones: hard caps on volume, a one-file kill-switch that halts every outbound path, dedupe ledgers, and a fail-closed check before any irreversible action. These hold whether or not a human is watching; a permission prompt does not, and it was never real safety for an unattended process.

3. Prove liveness by the work, not the process. A heartbeat that stamps on each real wake (before any gate) distinguishes "the process exists" from "the loop is actually cycling." When the heartbeat goes stale while the process is up, look INSIDE the session (capture its pane or state); do not trust the supervisor's "alive." A stale heartbeat behind a live process is the exact fingerprint of a session frozen on a prompt.

The durable rule: an unattended agent session cannot answer a permission prompt, so it must be launched without one. Its safety then lives in coded caps and a kill-switch, and its health is proven by a per-cycle heartbeat, not by the process still being up.
