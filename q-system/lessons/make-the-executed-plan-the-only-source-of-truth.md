---
id: make-the-executed-plan-the-only-source-of-truth
kind: methodology
title: Make the Executed Plan the Only Source of Truth
date: 2026-11-07
---

When work is driven by a plan file and executed in discrete sessions, coverage gaps and stalls usually come from six repairable mechanics. Apply them as a checklist.

1) Route every decision into the artifact the work reads.
When a decision is made, edit the file the executing session actually opens and follows, in the same turn. Narrative or scoping documents are not execution inputs. If a decision only exists as prose somewhere else, treat it as not made. A quick test: name the file a worker will open first; if the decision is not in that file, it will not be applied.

2) Give the plan an explicit input-to-objective map.
Structure the plan as a table where each row names one input source or tool and the specific question it answers. Omissions become visible as missing rows rather than invisible absences. Without this map, a source that was never considered looks identical to a source that was deliberately excluded, so record exclusions as rows with a reason rather than by deletion.

3) Run a readiness preflight before planning, not during execution.
Write one script that verifies every dependency the plan could call: credentials present and non-empty, quota or budget headroom remaining, background daemons and services running, network paths reachable. Run it at session start and have it print a pass/fail line per dependency. Discovering a dead credential or an exhausted budget mid-plan forces re-planning at the worst moment; discovering it in the first minute only costs a substitution. Include consumable limits explicitly, since a quota that was fine last week may be spent.

4) Convert mandatory first steps into enforced gates.
Labeling a step non-negotiable in documentation does nothing. A mandatory step needs a machine check: a hook, a wrapper, or a precondition that refuses to proceed until the step's output artifact exists. Design the gate around a durable, listable artifact, so after the fact you can list the output directory and tell at a glance whether the step ran. If a required step leaves no trace, you cannot audit it and it will be skipped.

5) Keep ergonomic parity across sources so tooling does not choose scope.
Work follows the path of least resistance. If two sources have convenient saved-result wrappers and the rest require ad-hoc construction, output will concentrate on those two regardless of what the plan says. Either build thin wrappers of comparable convenience for every source the plan names, or move the unsupported ones out of the plan and record them as deferred. Audit this by comparing the list of helper scripts against the list of planned sources; an asymmetry there predicts the coverage you will actually get.

6) Maintain the plan as a living document.
Mark phases done as they complete, and delete or strike phases that have been ruled out. A plan that visibly lags reality trains readers to skim it, and once skimmed it stops constraining the work. Make plan reconciliation the closing action of every session rather than a separate cleanup task.

7) Close the loop with a coverage diff.
At session end, compare sources actually used against sources planned and against sources available. Any discrepancy is either a finding to record or a gap to schedule. Repeated stalls in the same place indicate a missing preflight check, not bad luck, so add the check rather than retrying.
