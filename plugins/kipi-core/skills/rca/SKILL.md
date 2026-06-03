---
name: rca
description: "Root-cause analysis for code. Use when a defect shipped and was caught after the fact, a run came back BLOCKED or a deliverable failed validation, a bug recurs after a prior fix, or the user says 'rca this', 'root cause this', 'postmortem this', or 'why did this break'. Produces a structured RCA that separates surface from structural cause, demands evidence-backed verification, and tracks action items. Also covers prospective premortems."
---

# RCA Skill

The diagnostic counterpart to forward planning. When a failure gets past a test,
a gate, or review, write a root-cause analysis to the canonical template. The
goal is never who, it is: what guardrail was missing and why the mistake was
easy to make.

## Before writing

Read `references/rca-template.md`. It is the canonical structure and the exact
contract the lint enforces. Do not improvise a different shape.

## When to write an RCA

- A defect shipped and a human or a gate caught it after the fact.
- A run came back BLOCKED, or a deliverable failed validation.
- A bug recurs after a prior fix (the prior fix treated a symptom).
- The user says "rca this", "root cause this", "postmortem this", "why did this break".

A trivial bug you fix in the same breath, that never escaped a gate, does not
need an RCA. A failure that got past a test, a gate, or review does.

## Where RCAs land

`q-system/output/rca/rca-<slug>-<YYYY-MM-DD>.md` inside a kipi instance, or
`rca/rca-<slug>-<YYYY-MM-DD>.md` in a plain repo. The lint fires on any file
named `rca-*.md` / `premortem-*.md` or any doc whose H1 starts with `# RCA:` or
`# Premortem`.

## The rules the lint enforces

1. **Surface vs structural root cause.** Surface is the trigger (what fired).
   Structural is the latent systemic cause (why it was allowed and went uncaught).
2. **Multi-factor.** Use `### Root cause #1`, `### Root cause #2` when more than
   one structural cause contributed. Resist a single tidy cause.
3. **Cause-type tags.** Each structural cause carries a `type:` line, one of:
   code-defect, config, environmental-trigger, missing-test, implicit-contract,
   process, capacity.
4. **Verification is evidence.** Show the command and result ("ran X, got Y") or
   the passing test. An assertion with no observed output is not verification.
5. **Action items are checkboxes with owners.** Not prose. An RCA is not finished
   until its actions are owned and trackable.
6. **Blameless.** Describe system, contract, gate, and test failures. Never name
   a person as the cause.

## The deterministic notify

The `rca-notify` hook watches command results. When a test or run fails
(non-zero exit, or FAIL / BLOCKED / Traceback in the output), it injects a nudge
to open an RCA. That is the shoulder-tap. The skill is how you answer it.

## Premortem variant

Before shipping a high-trust deliverable, run a premortem instead: assume it
already failed in front of the customer and enumerate how. Structure is in the
template under "Premortem variant".

## Enforcement

`scripts/rca-lint.py` validates every RCA/premortem doc on write. Bypass a
single file with `<!-- rca-lint-skip -->` (intentional exceptions only).
