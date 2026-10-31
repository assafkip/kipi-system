---
id: enumerate-integrations-before-granting-automation-access
kind: pattern
title: Enumerate Integrations Before Granting Automation Access
date: 2026-10-31
---

When an automated agent is allowed to act on a user or service account, its real capability is the full set of integrations attached to that account, not the subset you remember configuring. Hand-maintained allow/deny lists drift and routinely cover only a fraction of what is actually installed, so treat enumeration as the first step and denial as the default.

How to apply it:

1. Enumerate from the platform, not from docs. Query the account's integration/connector listing API or admin console to get the authoritative inventory. Record the count. If your existing policy list is shorter than the inventory, treat every unlisted item as unreviewed.

2. Classify by blast radius, not by name. For each integration, ask what irreversible or outbound action it can take: sends messages to third parties, mutates production state, triggers deploys, executes arbitrary code, moves money, or changes permissions. Anything in those classes needs explicit review before it is reachable.

3. Invert the policy to default-deny. Express the rule as "block unless on the reviewed allow list" rather than "block if on the known-bad list." This makes new, unknown integrations fail closed instead of silently inheriting access.

4. Close the time-of-check gap. An integration added after an audit can execute at least once before the next audit notices it. Reduce that window by re-enumerating at agent start-up or per session, and by subscribing to platform events for integration installs where available. Compare each run's inventory against the last and alert on additions.

5. Record the audit as data. Persist the inventory snapshot with timestamps and review decisions so drift is diffable and the allow list has a provenance trail rather than being tribal knowledge.

6. Verify by negative test. Attach a new benign integration and confirm the agent is blocked from using it without a human review step. If it is permitted, the policy is still an implicit allow-list.

The general principle: for any capability surface that third parties can extend at runtime, enumerate from the source of truth, deny the unenumerated, and re-enumerate often enough that the gap between additions and detection stays smaller than the damage one call can do.
