---
id: separate-capability-from-orchestration-before-you-call-it-a-
kind: methodology
title: Separate capability from orchestration before you call it a gap
date: 2026-07-06
---

When one system produces a better result than another and you set out to explain why, resist the first-pass conclusion that the winner has capabilities the loser lacks. Two systems can hold the identical set of underlying abilities and still diverge sharply in output, because the difference lives in how the work is orchestrated, not in what the work can do. Treat capability and orchestration as two independent axes and diagnose them separately.

HOW TO DO IT:

1. List the observed behavioral differences first, before assigning any cause. Keep the list to concrete, observed facts, not interpretations.

2. For every difference you are tempted to call a missing capability, verify it against the actual implementation, not against your mental model or a quick read. Open the code or config that would provide that ability and confirm it is truly absent. Expect a meaningful fraction of your first-pass 'it can't do X' claims to be false. A capability that exists but never gets exercised looks identical to a missing one from the outside.

3. Once capabilities are confirmed equal, look at the orchestration layer, where real divergence usually hides. Common structural axes: does the process run as discrete phases with checkpoints between them, or as one continuous pass? Is there a review or approval gate between stages, or does it run unattended end to end? Is it bounded by a hard wall-clock kill, or allowed to run to completion? A hard timeout with no inter-phase checkpoints is a fundamentally different execution shape than an un-timed, gated sequence, even when both call the same tools.

4. State the root cause in structural terms. 'System A gates and checkpoints between phases while System B runs headless under a fixed time budget' is an actionable finding; 'System A is more capable' is not, and it points you at building features you already have instead of fixing how you run them.

WHY IT MATTERS: misattributing a structural gap to a capability gap sends you to add abilities that already exist while the real lever, the run structure, goes untouched. Validating claims against the artifact strengthens the analysis rather than weakening it, because a confirmed 'the capability is present' narrows the cause to orchestration and tells you exactly where to intervene.
