---
id: offload-mechanical-tail-work-to-a-fresh-cheap-agent
kind: pattern
title: Offload Mechanical Tail Work to a Fresh Cheap Agent
date: 2026-11-03
---

When a working session has accumulated a long history, each additional step costs more because the whole context is re-read before anything happens. Once the remaining work is mechanical, stop paying that cost and hand it off.

HOW:
1. Watch for the signal: the session has run long, and the steps still outstanding are repetitive loops — apply change, run build/deploy, check result, retry on failure — rather than reasoning that depends on earlier discussion.
2. Classify the remaining work. A step is offloadable if it can be described fully in a short brief: exact commands, success criteria, retry rules, and stop conditions. If describing it requires replaying the reasoning that built up over the session, keep it in place.
3. Write the brief as a standalone instruction set. Include the goal, the ordered steps, what counts as done, what counts as a hard failure, how many retries are allowed, and what to report back. Assume zero shared memory.
4. Start a fresh agent on a cheap, fast model with only that brief. Do not pass the long history; passing it defeats the purpose.
5. Require a single consolidated report at the end instead of running commentary — one summary of what succeeded, what failed, and any output you need to act on.
6. Review the report in the original session and resume judgment work there if anything non-mechanical surfaced.

WHY IT WORKS: cost and latency scale with context size per step, so repeated steps in a long session are the most expensive work you can do. Mechanical loops have low context requirements, so they are the cheapest thing to relocate and the most expensive thing to leave in place.

LIMITS: do not offload steps that need accumulated judgment, undocumented conventions discovered mid-session, or decisions where a wrong call is hard to reverse. If you cannot write the brief in a few paragraphs, the work is not mechanical yet — finish narrowing it first.
