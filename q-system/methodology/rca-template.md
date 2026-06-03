# Canonical RCA Template & Methodology

The canonical way to run a root-cause analysis on code in this system. Extracted
from the proven RCA practice in the ktlyst product (`docs/rca/`,
`scripts/rca_deliverable.py`) and grounded in the FAANG postmortem lineage
(Google SRE trigger-vs-root-cause, Amazon COE multi-factor) and the academic
fault-localization lineage. See `q-system/research/code-rca-resources-2026-06-02.md`.

An RCA written to this template passes `rca-lint.py`. The lint is the contract;
this file is how to satisfy it.

## When to write an RCA

- A defect shipped and a human or a gate caught it after the fact.
- A run came back BLOCKED or a deliverable failed validation.
- The founder says "rca this", "root cause this", or "why did this break".
- A bug recurs after a prior fix (the prior fix treated a symptom).

One-line trivial bug that you fix in the same breath does not need an RCA. A
failure that got past a test, a gate, or review does.

## Where RCAs land

`q-system/output/rca/rca-<slug>-<YYYY-MM-DD>.md`. `output/` is instance-local and
gitignored; RCAs are not skeleton content. For a prospective analysis (before
shipping), use the premortem variant at the bottom.

## The blameless rule (non-negotiable)

Describe system, contract, gate, and test failures. Never "engineer X failed".
The question is never who, it is: what guardrail was missing, why was the mistake
easy to make, why did the test or gate not catch it. A person-named cause is a
lint failure.

## Required structure

Copy this. Every `##` header below is required. The lint checks for them.

```markdown
# RCA: <one-line symptom, not the cause>

**Date:** YYYY-MM-DD
**Trigger:** <what surfaced it — a founder observation, a gate, a failing run>
**Surface-fix commit:** <sha or "pending">
**Structural-fix commit:** <sha or "pending">

## What happened

Two to four sentences. The customer- or founder-visible failure, concretely.
What was expected, what actually occurred.

## Surface symptom

The observable artifact of the failure: the empty panel, the BLOCKED verdict,
the wrong field. Show it (a path, a snippet, a log line), do not describe it.

## Surface root cause

The immediate, proximate cause — the trigger. The specific line, field, config,
or change that fired the failure. This is the "what broke", not the "why it was
allowed to break".

## Structural root cause

The latent, systemic cause — why the surface cause existed and went uncaught.
Multi-factor is expected: use `### Root cause #1`, `### Root cause #2` when more
than one structural cause contributed. Resist a single tidy cause.

Classify each cause with a type tag on its own line:
`type: code-defect | config | environmental-trigger | missing-test | implicit-contract | process | capacity`

The environmental-trigger vs latent-defect split (from the product's
stack-driven vs producer-defect classification) matters: an environmental
trigger clears when the environment changes; a latent defect persists anywhere.

## Verification

Did the fix actually resolve it. Evidence, not assertion. Show the command and
the result ("ran X, got Y"), or paste the passing test / clean run. A claim with
no observed output is not verification.

## Contributing factors

What let it through: a missing test, an implicit (untested) contract, an
advisory-not-enforced gate, weak monitoring, a risky merge. Each is a candidate
for an action item.

## Fixes shipped

- Surface fix: <what + commit>
- Structural fix: <what + commit — the change that prevents the class, not the instance>

## Action items

First-class and trackable. Each is a checkbox with an owner. Not prose.

- [ ] <action> — owner: <who> — <type: test | gate | code | process | doc>
- [ ] ...

## Lessons

What the next person should know. One to four bullets. No filler.
```

## Why first-class action items

The gap in the existing practice was action items living as "what to do next"
prose. Prose action items do not get tracked to closure. The lint requires the
`## Action items` section to contain real checkboxes (`- [ ]`), matching the
FAANG norm that an RCA is not done until its actions are owned and tracked.

## Premortem variant (prospective)

Before shipping a high-trust deliverable, run a premortem instead: assume it
already failed in front of the customer, enumerate how. Structure:

```markdown
# Premortem: <deliverable>

**Date:** YYYY-MM-DD
**Trigger:** premortem before <ship event>

## Findings by severity

### CRITICAL — would invalidate the trust narrative
### HIGH — would surface as a defect on careful review
### MEDIUM — manageable risk
### LOW — operational hygiene

## Cross-cutting patterns

Named recurring shapes (e.g. brand-without-substance, static-posing-as-dynamic,
detector-exists-enforcement-advisory).

## Recommended fix order

## What I did NOT find

State the surface you checked and found clean, so the premortem's scope is legible.
```

## Relationship to other parts of the system

- `quick-plan.md` is forward (how to build). RCA is backward (why it broke).
- `prd-os` owns gated product changes; an RCA's structural fix often becomes a PRD.
- `rca-lint.py` enforces this template's required sections deterministically.
