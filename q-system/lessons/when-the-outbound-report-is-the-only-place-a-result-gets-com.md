---
id: when-the-outbound-report-is-the-only-place-a-result-gets-com
kind: pattern
title: When the outbound report is the only place a result gets computed
date: 2026-09-14
---

A report you send outside the team times out. The obvious fix is to make it faster. First check a different question: is generating that report the first moment anyone sees the result it contains?

## The shape

A system has two kinds of views:

- **Per-item views** that reviewers use every day, one record at a time.
- **An aggregate computation** that runs across a whole group of records.

List every call site of the aggregate computation. Sometimes the only real caller is the outbound document, and the rest are side tools like a tuning sandbox. In that case, generating the report is not rendering a result someone already checked. Generating the report IS the computation. Nobody inside the team saw the number before the recipient did.

Making that path fast keeps the order backwards. The reviewer still decides after the external artifact already exists.

## Why the failure stays invisible

No internal job waits on that path, so no reviewer is blocked when it times out and nobody complains. A path that is not part of anyone's daily work is effectively unmonitored, whatever dashboards exist. Long silence from a slow path tells you nobody depends on it. It does not tell you the path is healthy.

## Check before you build the missing view

- Look at the internal workflow where the aggregate should live. If it holds a placeholder, read why. The usual reason is missing inputs: a field name the reader expects that differs from the one the writer stores, or a field that no data source populates. Those gaps are why the internal view was never built, so fix them first.
- Before you delete a module as unreachable, check the call graph by hand. Static wiring audits miss calls made through an aliased import. When the audit and the written documentation disagree, check the code, and do not assume the audit is right.

## Bound the loop by time, not only by money

A loop over a group of records with a spend cap can still run longer than the caller's request timeout. Give every aggregate loop a wall-clock budget that fits its caller's timeout. Move large groups to a background job that stores the result.

## How to apply

1. For any outbound artifact, list the internal surfaces that show its key numbers first. If none exist, treat that as the defect, not the latency.
2. Build the aggregate view reviewers use. Store its reviewed result and have the report read that stored result instead of recomputing it.
3. Check that every input the aggregate needs can actually be read, with matching field names end to end.
4. Set a time budget on every aggregate loop, alongside any cost budget.
5. When an audit calls something unreachable and the docs disagree, trace the import by hand before you remove anything.
