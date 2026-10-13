---
id: verify-cost-and-safety-controls-by-observing-real-executions
kind: methodology
title: Verify cost and safety controls by observing real executions, and give every detector an owner
date: 2026-10-12
---

A recurring cost leak after a supposed fix usually traces to four gaps in how controls are verified and operated.

1. Test the behavior, not the source. A scanner that treats a call site as protected because the file mentions the guard can be fooled: the guard may sit behind an early return that the main path always takes, and the scanner may skip whole directory trees (for example, linked worktrees) where the live code actually runs. Add an end-to-end check that performs one real call through each production entry point and asserts that the expected side effect (such as a ledger or metering record) appeared. Before trusting any check, ask whether some realistic input could turn it red for the exact defect you care about. If not, it is not a test of that defect.

2. Every detector needs a drain. A report that says most items are non-compliant, unchanged for days, is not coverage. Assign an owner or an automated job that converts findings into fixes, track the count over time, and fail or escalate when it does not fall.

3. Give background work an explicit lean contract. Headless or scheduled invocations that reuse the interactive tool's default setup inherit its hooks, rules, and context files, so their per-call cost grows silently as that setup grows, with no change to the job itself. Define that background calls run from an empty working directory with settings, extensions, and tools disabled unless needed, and add a test that measures baseline setup cost (for example, tokens for a trivial prompt) against a budget.

4. Meter every spender and scope delegated work narrowly. Delegated or sub-agent usage that bypasses the usage ledger makes the largest consumers invisible to whoever watches the meter. Route all such usage through the same metering, and make sure the rule 'one fresh agent per task' is applied per actual task, not per brief that bundles several jobs. Check that the intent of a corrective action, not just its wording, was implemented.

General principle: a fix is only done when a real execution demonstrates it, something owns the remaining gap, implicit contracts are written down and tested, and all spend is measured.
