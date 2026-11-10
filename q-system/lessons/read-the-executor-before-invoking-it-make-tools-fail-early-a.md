---
id: read-the-executor-before-invoking-it-make-tools-fail-early-a
kind: methodology
title: Read the executor before invoking it; make tools fail early and say what they accept
date: 2026-11-10
---

When a multi-step tool (a sync, land, or deploy script) fails repeatedly, the cheapest fix is usually to read it before running it again.

1. Read before the first invocation. Before running an unfamiliar executor script, read its source end to end. A few hundred lines is one read. Each blind trial run is one full run that may leave state behind. Make this a standing rule in any orchestration flow: no first invocation without reading the executor. Do not iterate by guessing at arguments.

2. Handle every change type explicitly. A planner that selects changed items through a set operation (for example, items present at the source AND differing now) will often include deletions without handling them. Enumerate add, modify, delete and rename. Give each one an explicit path or an explicit refusal. Never let the classifier mark an unsupported change type as clean or ready.

3. Refuse during planning, not mid-execution. Validate everything that could be rejected during the classify/plan phase, before any side effect such as creating a branch, worktree, temp directory or remote resource. A late refusal leaves partial artifacts behind, and the next run then has to work around them.

4. Document the argument contract and enforce it. If a flag accepts only file paths, say so in the help text. Reject directories, or expand them, rather than silently matching nothing. A no-op verdict such as 'unchanged' or 'nothing to do' for input the tool did not understand is the most misleading result possible. Distinguish 'nothing matched' from 'nothing changed' in the output.

5. Make setup idempotent. If the tool creates a branch or workspace, let it detect and reuse an existing one, or fail with a clear message naming the leftover artifact. Do not depend on deleting it. Guardrails often block destructive cleanup, so a tool that can only create fresh state forces renaming workarounds after every failed run.

6. In the RCA, separate the causes into code defects (missing paths, non-idempotent setup), implicit contracts (undocumented inputs) and process gaps (running before reading). Each needs a different fix, and fixing only the code leaves the next operator guessing again.
