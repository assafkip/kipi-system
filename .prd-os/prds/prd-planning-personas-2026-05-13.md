---
id: prd-planning-personas-2026-05-13
title: Planning Personas in prd-os Draft Phase
status: archived
created_at: 2026-05-13
updated_at: 2026-05-14T15:15:09Z
owner: assaf
reviewers: []
findings_path: .prd-os/findings/prd-planning-personas-2026-05-13-findings.jsonl
codex_reviewed_at: 2026-05-14T15:12:51Z
---

# Planning Personas in prd-os Draft Phase

## Problem

PRDs in kipi sometimes reach `/prd-review` without enough adversarial thinking up front. Codex catches issues at the review gate, but Codex is downstream. By the time Codex flags a vague success criterion, an unstated user, or a missing failure mode, the founder has already committed cognitive cycles to a specific direction. Revising at that stage costs more than asking the right question during the draft state.

Observed pattern across recent PRDs (this one included, before agent-team review):
- Goals stated in implementation language ("add command X") rather than outcome language ("founder catches Y class of issue before Codex")
- Non-goals section left empty, which means scope is implicitly unlimited
- "Risks and rollback" treated as a checkbox rather than a real exposure assessment
- Open questions resolved silently between sessions without the founder confronting them explicitly

The most established analog in the public ecosystem, BMAD-METHOD (47K stars, bmad-code-org/BMAD-METHOD), addresses this through dedicated agentic personas (PM, Architect, Analyst, UX) that collaborate during planning. Kipi has the council skill in kipi-ops, but council is built for strategic decisions on canonical files, not PRD shaping on a draft spec, and is not wired into the prd-os state machine.

This PRD proposes the smallest version of planning personas that can prove the value: one persona, three pinned questions, no infrastructure beyond a single new command.

## Goals

**Primary outcome (single success metric, operationalized):**

A Codex finding counts as "vague-goal" if its `body` text contains any of: "vague", "not measurable", "unclear what success", "no metric", "operationalized", "outcome-focused", "implementation-focused", OR if it cites the rubric's "Problem clarity" dimension. A finding counts as "empty-non-goals" if its body contains any of: "non-goals", "scope creep", "scope discipline", "unbounded scope". Classification is done at triage time by reading each finding's `body` field.

The success metric is: across 5 consecutive PRDs that ran the persona session in v0, the rate of vague-goal-class plus empty-non-goals-class findings is at least 50% lower than the same rate measured over the 5 most recent PRDs that did NOT run the persona session (the baseline). If the reduction is below 50%, the experiment is killed and rolled back per the Rollback section.

Baseline measurement: before /prd-personas ships, the 5 most recent merged PRDs in `.prd-os/prds/` have their findings JSONL files scanned and classified using the same rule above. The resulting baseline rate is recorded in `q-system/memory/working/prd-personas-baseline.md`. This is Phase 0 below.

Supporting outcomes:
- Founder confronts at least one strong counterargument to the PRD before invoking Codex.
- The Persona Review section is a durable record of what was already considered, visible inside the PRD spec to future readers and to Codex review.

## Phase 0: Template-only baseline (added in response to finding-3)

Before any code ships, run a 2-week template-only experiment to test whether the cheaper alternative solves the problem unaided:

1. Add a `## Persona Review` section template to `q-system/marketing/templates/prd.md` and `plugins/prd-os/templates/prd.md` with the 3 Skeptic questions as commented-out placeholders.
2. For 2 weeks (or 3 PRDs, whichever comes first), the founder fills in the section manually before /prd-review, using the template as a checklist. No command, no persona file, no plugin code.
3. Measure: do the new PRDs reduce vague-goal-class + empty-non-goals-class findings vs the baseline?
4. Kill criterion: if the template-only approach achieves the 50% reduction target, this entire PRD is rolled back to the template change only. No command. No persona file. No plugin code. The PRD is archived as "solved by cheaper alternative" and the rest of the work is not built.
5. Continue criterion: if the template-only approach does not hit 50% reduction, proceed to v0 implementation (the new command + Skeptic persona file).

Phase 0 is a deliberate hedge against over-building. The Phase 0 result determines whether the rest of the PRD ships.

## Non-goals

- Replacing Codex adversarial review at the `/prd-review` gate. Personas surface thinking; Codex still adversarially reviews the final PRD against the rubric.
- Multi-LLM debate. This stays single-Claude. The persona work is about loading sharper question patterns into context, not consensus mining across providers.
- Forcing personas on every PRD. Small PRDs (bug fixes, minor tweaks) skip this step. The command is optional and invoked explicitly.
- New state transitions in the PRD state machine. The PRD stays in `draft` throughout. Persona Review is content, not state.
- Multi-user support. v0 is founder-only. Multi-user persona handling is parked.
- Auto-detection of "this PRD needs personas." The founder decides when to invoke.
- Modifying the Codex review rubric. The footgun of downgrading findings that contradict persona answers is explicitly rejected; v0 does not touch the rubric.
- Modifying the `/prd-review` command with a nudge. v0 does not couple review to personas.
- Reusing or merging with the council skill in kipi-ops. v0 keeps them separate; convergence is parked work (see Open questions).
- Adopting BMAD wholesale. Separate evaluation, not part of this PRD (see Open questions).

## Proposed approach

### v0: One persona, three pinned questions, no auto-skip

The smallest viable experiment is a Skeptic persona only, with three pinned questions that never get auto-skipped:

1. "What is the strongest argument against doing this?"
2. "What is the smallest experiment that would disprove the thesis?"
3. "What is the cheapest non-build alternative?"

The Skeptic was picked over PM and Architect for v0 because the Problem section is specifically about PRDs going to review without enough adversarial thinking. The Skeptic lens is the most direct fit. PM and Architect add value but are not on the critical path for the named failure mode.

### New command

`/prd-personas` in `plugins/prd-os/commands/prd-personas.md`. Requires the active PRD to be in `draft` state, otherwise refuses with the current state and a hint.

### Persona definitions

New directory `plugins/prd-os/personas/` with one markdown file: `skeptic.md`. Each persona file declares:
- Persona name and one-line role
- A pinned list of questions (never auto-skipped, always asked verbatim)
- Anti-patterns the persona watches for

For v0, only `skeptic.md` ships. PM and Architect personas can ship in v1 if v0 succeeds against the primary outcome metric.

### Session flow

When `/prd-personas` runs:
1. Read the active PRD spec via `prd_runner.py status` (same active-PRD contract every other prd-* command uses).
2. If the PRD is not in `draft` state, refuse with the current state and a hint to run `/prd-revise` if needed.
3. For each pinned question, present it to the founder one at a time.
4. Founder answers in conversation. Brief is fine. "Skip" is allowed but the question is still recorded as "skipped" rather than removed.
5. After all questions, write the section to the PRD per the rerun rules below.
6. Update the PRD's `updated_at` frontmatter field and save.

No precheck heuristic. No "already-answered" skip logic. v0 explicitly trades founder time (~5 min per session) for predictability. If the questions feel repetitive after running on real PRDs, that's a v1 improvement, not a v0 risk.

### Rerun, interruption, and dup-section handling (added in response to finding-5)

- **First run:** if no `## Persona Review` section exists in the PRD, append a new section with one `### Skeptic` subsection containing the Q-A pairs.
- **Rerun on the same PRD:** if a `## Persona Review` section already exists, append a new timestamped subsection: `### Skeptic (rerun YYYY-MM-DDTHH:MM:SSZ)`. Original answers stay; the new run does NOT overwrite. This makes the section additive and gives the founder visibility into how their thinking changed across runs.
- **Interruption:** if the founder ctrl-c mid-session or the session ends before all questions are answered, NOTHING is written to the PRD. Partial answers are not saved. The next /prd-personas invocation starts fresh.
- **Explicit abort:** if the founder types "abort" or "cancel" in the conversation, same behavior: nothing written.
- **Duplicate ## Persona Review headings:** the command must never write a second top-level `## Persona Review` heading. If one exists, append subsections to the existing section. The duplicate-heading detector that already exists for `## Issues` does not currently cover `## Persona Review`, but the command-side logic prevents it by construction.

### Placement of the Persona Review section

The new section sits immediately before `## Issues` in the PRD spec. Order of sections after the change:

1. Problem
2. Goals
3. Non-goals
4. Proposed approach
5. Risks and rollback
6. Open questions
7. **Persona Review** (new, optional, only if `/prd-personas` was run)
8. Issues

This placement is chosen so that:
- The G6 manifest-status gate (commit c757a7e) at archive time and the duplicate-`## Issues`-heading detector (commit 5d8d4cf) are not affected. The Persona Review section is plain markdown and does not contain a `## Issues` heading.
- Codex review reads the section in context after the substantive sections (Problem through Open questions) and before the implementation manifest (Issues).
- `prd_split.py` (which reads the `## Issues` JSON block) is unaffected. Its parser anchors on the `## Issues` heading regardless of what precedes it.

### What does NOT change

- The PRD state machine. No new transitions. No new states.
- The review-rubric.md file. Codex review continues to score the PRD as-is, unaware of whether personas ran. (This was named as a footgun in agent review: downgrading findings that contradict persona answers would suppress legitimate Codex concerns exactly when the founder is overconfident. v0 does not do this.)
- The `/prd-review` command. No nudge. No coupling. If the founder forgot to run personas, that is the founder's call.

### Future work (not in v0, listed for context)

- PM persona (`plugins/prd-os/personas/pm.md`) with user-definition lens
- Architect persona (`plugins/prd-os/personas/architect.md`) with primitive-reuse lens
- UX persona (only when PRD has user-facing surface)
- Deterministic precheck: a typed mapping (persona question -> required spec section + non-empty content check) that can skip questions whose anchor section is non-empty AND passes a length threshold. Stays out of v0 because it is the load-bearing UX assumption and shipping it half-built would degrade the experience.
- Per-project persona overrides (precedence: project-local first, plugin default second)
- Wholesale BMAD evaluation as a spike: read BMAD's persona system, decide whether to adopt or continue building kipi-flavored. Parked separately.

## Risks and rollback

### Risks

- **Optional and short = used once, abandoned.** Even one persona with three questions might feel like ceremony. **Mitigation:** the v0 commitment is to run it on at least 5 PRDs and measure against the success metric before deciding to expand or kill. The founder pre-commits to the experiment, not to the long-term value.

- **Skeptic-only is too narrow.** A PM-shaped or Architect-shaped issue could pass Skeptic unchallenged. **Mitigation:** if v0 succeeds, v1 adds PM and Architect. If v0 fails the metric, the experiment dies, and the kipi-ops council skill remains for strategic-decision cases. Either way, no infrastructure is wasted.

- **Persona Review section conflicts with downstream PRD parsers.** Already addressed: section sits before `## Issues`, does not introduce a competing `## Issues` heading, and prd_split.py is unaffected. **Mitigation:** test before shipping by running prd_split.py against a PRD with a Persona Review section and confirming the issues block still parses.

- **Founder answers Skeptic questions superficially because they feel rhetorical.** "What is the strongest argument against this?" can be answered "nothing important." If that happens, the session adds noise without value. **Mitigation:** Voided 2026-09-18 (ASK-543), not observed. `parse_skeptic_answers()` over the 44 PRDs in `.prd-os/prds/` finds 13 recorded answer sets and zero trivial answers; the only non-substantive states are a blank `A1:` scaffold or an explicit written skip, which `phase0_measure.py` already counts as `no-personas`. A lint would have no real RED fixture to calibrate against and ships fleet-wide as a blocking hook. If a real trivial answer is ever recorded, it becomes the RED fixture of a new issue.

- **Overlap with council skill.** The council skill operates on canonical files and high-stakes strategic decisions. Planning personas operates on the active PRD draft. Different inputs, different outputs, different state machines. **Mitigation in v0:** keep them strictly separate; do not share persona files between systems. **Future work:** evaluate convergence as a separate spike after both have approximately 10 sessions of real use; either merge or keep separate based on evidence.

- **Rollback leaves orphan Persona Review sections in PRDs authored during the v0 window.** After rollback, future PRDs will not have these sections, but PRDs from the v0 window will. **Mitigation:** the section is plain markdown; no downstream consumer requires it; abandoned sections are forward-compatible noise, not broken state. Document this in the rollback procedure so future readers do not assume the section is meaningful.

### Rollback

- Delete `plugins/prd-os/commands/prd-personas.md`.
- Delete `plugins/prd-os/personas/` directory.
- Existing `## Persona Review` sections in past PRDs stay where they are (forward-compatible, no parser depends on them).
- No state machine changes to revert. No data migration. No external integrations.

Rollback cost is one git revert per file. Low blast radius. Documented orphan section is the only residual.

## Open questions

- **Should the persona session block `/prd-review` until it has been run at least once?** Resolved: no. Forcing the optional step makes it non-optional and is the wrong move for v0. The founder decides when to invoke.

- **Should personas be customizable per project (different KTLYST cluster instances might want different personas)?** Resolved: parked to v2. v0 ships one persona set in the plugin with no override path. v2 will add precedence rules (project-local first, plugin default second) if the need surfaces.

- **Should the Persona Review section be machine-validated for completeness (every persona must have at least one Q-A pair)?** Resolved: no for v0. Let founder shape the section freely. Add validation only if Codex review starts flagging incomplete persona sections as a pattern.

- **Does this duplicate `kipi-ops/skills/council`?** Different surface (PRD vs canonical decision), different timing (PRD shaping vs strategic shift), different output (PRD section vs council ruling). v0 keeps them separate. Convergence is a separate spike after both have approximately 10 sessions of real use.

- **Should a PM/Architect/UX persona ship in v0?** Resolved: no. v0 is Skeptic-only. The Problem section names adversarial-thinking-too-late as the failure mode; Skeptic is the most direct fit. PM and Architect add value but are not on the critical path. v1 expands if v0 succeeds against the metric.

- **Should BMAD's persona system be adopted wholesale instead of building kipi-flavored?** Parked as separate spike. Evaluating BMAD adoption is not blocking on this PRD. v0 ships its narrow experiment; BMAD spike is independent work.

## Persona Review

This section captures the agent-team persona review of this PRD, applied recursively (the proposed system, applied to its own PRD). Three personas (PM, Architect, Skeptic) reviewed the v0 draft before this revision. The revision incorporates their must-fix findings.

### Skeptic

**Q1: What is the strongest argument against doing this?**
The founder can solve the underlying problem (PRDs going to review without enough thinking) with a four-bullet checklist appended to the PRD template, zero new commands, zero new infrastructure. If the cheaper alternative is not run for two weeks first, this PRD is overbuilding. v0 addresses this by shipping the lightest possible infrastructure (one command, one persona file) and pre-committing to kill the experiment if the success metric fails.

**Q2: What is the smallest experiment that would disprove the thesis?**
Skeptic persona only, three pinned questions, no precheck heuristic, no rubric changes, no `/prd-review` coupling. Run on 5 PRDs. If Codex still surfaces vague-goal findings at the same rate as non-reviewed PRDs, kill the experiment. This is now the v0 scope.

**Q3: What is the cheapest non-build alternative?**
Adding the four bullet lenses to the prd-start skill's authoring guidance: "before invoking /prd-review, answer one Skeptic question, one PM question, one Architect question, one UX question if applicable." No command. No persona files. The author writes the answers into the existing PRD sections.

Decision: v0 ships the lightest infrastructure (one command, one persona file, no rubric or review coupling). If v0 fails the success metric, the fallback is to delete the command and add the four-bullet lens guidance to the prd-start template instead. The build/no-build evaluation is therefore part of the v0 success criterion.

## Issues

<!--
After review and approval, populate the fenced JSON block below with one
entry per atomic issue. `prd_split.py` reads this block verbatim and writes
one issue spec per entry.

Required keys per entry:
  - id (kebab-case, unique across the repo)
  - title (non-empty string)
  - allowed_files (non-empty list of glob patterns)
  - required_checks (non-empty list, e.g. ["pytest -q"]). The runner's
    stop-gate checks that three receipts are marked (verified, reviewed,
    findings_triaged). Those receipts are meaningless unless the spec
    documents what must be verified, so an empty list is rejected.

Optional keys:
  - priority (default p1)
  - disallowed_files, required_reviews, acceptance

IDs must match the repo's issue naming convention and must not collide with
existing issue specs.
-->

```json
[
  {
    "id": "prd-personas-baseline-and-classification",
    "title": "Operationalize success metric: baseline measurement script + classification rule",
    "finding_id": "finding-2",
    "priority": "p0",
    "allowed_files": [
      "q-system/memory/working/prd-personas-baseline.md",
      "plugins/prd-os/scripts/classify_findings.py",
      "plugins/prd-os/tests/test_classify_findings.py"
    ],
    "required_checks": [
      "test -f q-system/memory/working/prd-personas-baseline.md",
      "test -f plugins/prd-os/scripts/classify_findings.py",
      "pytest -q plugins/prd-os/tests/test_classify_findings.py"
    ],
    "acceptance": "classify_findings.py classifies a JSONL findings stream into vague-goal-class and empty-non-goals-class buckets via the body-text rules defined in the PRD. Baseline file records the rate across the 5 most recent merged PRDs. Test validates classification on a fixture."
  },
  {
    "id": "prd-personas-phase-0-template",
    "title": "Phase 0: add Skeptic question template to PRD templates, run 2-week template-only experiment",
    "finding_id": "finding-3",
    "priority": "p0",
    "allowed_files": [
      "q-system/marketing/templates/prd.md",
      "plugins/prd-os/templates/prd.md"
    ],
    "required_checks": [
      "grep -q 'Persona Review' plugins/prd-os/templates/prd.md",
      "grep -q 'Persona Review' q-system/marketing/templates/prd.md",
      "grep -q 'strongest argument against' plugins/prd-os/templates/prd.md"
    ],
    "acceptance": "Both PRD templates include a commented-out Persona Review section with the 3 Skeptic questions. Founder fills it manually on the next 3 PRDs and the result is measured against the baseline before any plugin code ships."
  },
  {
    "id": "prd-personas-command-implementation",
    "title": "Implement /prd-personas command + skeptic persona file + parser-compat test",
    "finding_id": "finding-1",
    "priority": "p1",
    "allowed_files": [
      "plugins/prd-os/commands/prd-personas.md",
      "plugins/prd-os/personas/skeptic.md",
      "plugins/prd-os/tests/test_prd_split_personas.py"
    ],
    "required_checks": [
      "test -f plugins/prd-os/commands/prd-personas.md",
      "test -f plugins/prd-os/personas/skeptic.md",
      "grep -q 'draft' plugins/prd-os/commands/prd-personas.md",
      "pytest -q plugins/prd-os/tests/test_prd_split_personas.py"
    ],
    "acceptance": "Command file documents draft-state-only invocation and calls prd_runner.py status for active-PRD discovery. skeptic.md declares the 3 pinned questions verbatim. Parser-compat test confirms prd_split.py handles PRDs with a Persona Review section. Only ships if Phase 0 fails the kill criterion.",
    "required_reviews": [
      "codex-review"
    ]
  },
  {
    "id": "prd-personas-rerun-and-abort-spec",
    "title": "Document rerun, interruption, abort, and dup-section handling in command spec",
    "finding_id": "finding-5",
    "priority": "p1",
    "allowed_files": [
      "plugins/prd-os/commands/prd-personas.md"
    ],
    "required_checks": [
      "grep -q 'rerun' plugins/prd-os/commands/prd-personas.md",
      "grep -q 'abort' plugins/prd-os/commands/prd-personas.md",
      "grep -q 'timestamped' plugins/prd-os/commands/prd-personas.md"
    ],
    "acceptance": "Command file documents: rerun appends timestamped subsection (not duplicate ## heading); interruption discards partial answers; explicit abort discards partial answers; never writes a second top-level ## Persona Review heading."
  }
]
```

