---
id: put-a-quality-judge-on-every-generation-path-not-just-the-pr
kind: pattern
title: Put a quality judge on every generation path, not just the primary one
date: 2026-10-12
---

When a system has several routes that produce generated content, quality checks tend to get attached to the route that was built first or is most formal, while secondary or ad hoc routes ship without them. Often the route people actually use most is the one with the least review. Structural checks (format, schema, lint-style gates) passing says nothing about whether the output is good, so a run reporting 'all gates clean' can still be wrong.

How to apply it:
1. Inventory every path that produces user-facing output and list which evaluators (fidelity, style, correctness critics) run on each. Look for gaps, especially on the most-used path.
2. Separate structural validation from semantic judgment. Treat structural passes as necessary, never as acceptance. Record them under a different name than 'approved'.
3. Make evaluators shared components that every path calls through a common entry point, so a new path cannot bypass them silently. If a path must skip judgment, make that an explicit, logged exception.
4. Run an end-to-end check at least once per path: generate a real batch, have the judge (or a human) grade it, and compare against the structural verdict. Disagreements show where the gates are blind.
5. Keep the acceptance trail honest: store the judge's verdict and rationale next to the gate results, so a later review can tell 'checked and good' from 'only structurally valid'.
6. When a root-cause review repeats the same finding, escalate it into a tracked work item with an owner. Restating the finding in each review without a fix means the process is not closing the loop.
