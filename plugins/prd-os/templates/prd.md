---
id: {{prd_id}}
title: {{title}}
status: idea
created_at: {{created_at}}
updated_at: {{created_at}}
owner: {{owner}}
reviewers: []
findings_path: .prd-os/findings/{{prd_id}}-findings.jsonl
---

# {{title}}

## Problem

<!-- What pain is this solving? Concrete, observed, measurable. -->

## Goals

- 

## Non-goals

- 

## Proposed approach

<!-- How. Keep it scannable. Diagrams go inline as fenced blocks. -->

## Alternatives considered

<!--
Options you weighed and rejected. For each: name the option, the tradeoff, and
the one reason it lost. This is what lets the reviewer tell a deliberately
rejected path from one you never saw. Empty here reads as "no alternatives
exist," which is rarely true.

- **<option>** — Rejected: <why>.
-->

## Scenarios

<!--
Concrete end-to-end walkthroughs of the approach in use. One per distinct path.
Actor, trigger, steps, outcome. Prove the approach against the real flow, not
the abstraction.

- **<scenario name>.** <actor> does <trigger>; <steps>; <outcome>.
-->

## Resolved decisions

<!--
The counterpart to Open questions: decisions now closed, each with its
rationale. This is the running record of what was settled and why, so it does
not get re-litigated later.

- **<decision>.** Decided: <choice>. Rationale: <why>.
-->

## Risks and rollback

<!-- Blast radius, migration cost, how to back out if this ships wrong. -->

## Open questions

- 

<!--
## Persona Review (optional, fill in before /prd-review)

Phase 0 of the prd-os planning-personas experiment (PRD prd-planning-personas-2026-05-13).
For non-trivial PRDs, answer the three Skeptic questions below before invoking /prd-review.
Brief answers are fine. The goal is to force one round of adversarial thinking before Codex.

### Skeptic

Q1: What is the strongest argument against doing this?
A1:

Q2: What is the smallest experiment that would disprove the thesis?
A2:

Q3: What is the cheapest non-build alternative?
A3:

When done with these questions, uncomment this section and move it to live just before `## Issues` below.
-->

## Issues

<!--
After review and approval, populate the fenced JSON block below. The manifest is
read by TWO consumers and every entry must satisfy both:
  - `prd_split.py` materializes one issue spec per entry (needs `id`).
  - the approval gate proves every ACCEPTED finding is covered by an entry (needs
    `finding_id` + a `bypass_check`). One entry per accepted finding.

Required keys per entry (spine-native -- both consumers):
  - id (kebab-case, unique across the repo)            -- prd_split.py
  - finding_id (the accepted finding it covers, e.g. "finding-1") -- approval gate
  - title (non-empty string)
  - allowed_files (non-empty list of glob patterns)
  - required_checks (non-empty list, e.g. ["pytest -q"]). The stop-gate checks
    three receipts (verified, reviewed, findings_triaged); they are meaningless
    unless the spec documents what must be verified, so an empty list is rejected.
  - bypass_check (a command proving no bypass remains) OR
    bypass_exempt: "<reason>"                          -- spine contract

Optional keys:
  - priority (default p1)
  - disallowed_files, required_reviews, acceptance

Authoring a manifest with `id` but no `finding_id` (the pre-spine shape) is
rejected at approve. The template-vs-runner contract test enforces this list.
-->

```json
[]
```
