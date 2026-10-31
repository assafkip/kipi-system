---
id: gates-must-recompute-not-read-self-reports
kind: pattern
title: Gates Must Recompute, Not Read Self-Reports
date: 2026-10-31
---

## Problem

An automated quality gate guards a pipeline, yet broken work passes. The gate's checks look thorough: a dozen conditions, each required. But they fail as a class, not individually.

Sort every check by **who produced the thing the check reads**:

| Gate derives it at check time | Gate reads an artifact and trusts its author |
|---|---|
| Recomputes a hash of the output and compares | Reads a `passed: true` flag from a status file |
| Extracts a quote from the output and matches it against the live source it claims to quote | Reads a list of deficiencies the producer chose to emit |
| Confirms a required marker exists in the actual output bytes | Confirms a report file exists and is non-empty |
| | Reads prose claims: "reviewed", "approved", "addressed", a signed-off date line |

The left column holds under pressure. The right column holds only while the thing being constrained chooses to cooperate. If the producer and the attestor are the same actor, the check is a formality — it verifies the *account of the work*, not the work.

Two distinct failure modes recur:

1. **Self-attestation accepted as evidence.** The gate reads a file the producer wrote about its own output.
2. **Independent judges collected but never read.** Linters, analyzers, reviewers, or external validators run, and the gate requires their reports to *exist* — but never parses the verdict inside. The one instrument positioned to catch the defect is reduced to a file-existence check.

A common amplifier: the gate's own documentation states an assumption like "the sealing step runs the whole chain before writing a receipt, so a fresh receipt proves the chain ran." Nothing enforces that only the sealing step can write a receipt. The invariant lives in a comment, not in the mechanism.

## How

**1. Audit by producer, not by coverage.** For each check, write down who produced the bytes it reads. Any check whose input was authored by the actor under test is a formality until proven otherwise. Count them. The ratio is your real gate strength — not the number of checks.

**2. Convert self-reports into recomputations.** For each right-column check, ask: *can the gate derive this from the artifact itself?* Usually yes, and cheaply:
- Instead of trusting a "tests passed" flag, run the tests from inside the gate and read the exit code.
- Instead of trusting a reported count, recount from the raw artifact.
- Instead of trusting "this quotes the spec," extract the quoted span and match it against the live spec at check time.
- Instead of trusting "output unchanged since validation," hash the output now and compare to the hash recorded at validation.

**3. Read the verdicts you already pay for.** For every external tool in the pipeline, the gate must parse its output and branch on the result — not assert the file exists. Treat an unparsed report as an absent check. Make the gate fail closed on a report it cannot parse, an unexpected schema, or a missing field; a malformed verdict must not read as a pass.

**4. Make provenance unforgeable, or stop claiming it.** If a token (receipt, seal, approval record) is meant to prove a process ran, bind it to that process: sign it with a key the constrained actor cannot reach, emit it from a separate privileged step, or derive it from inputs only that step can observe. If you cannot bind it, delete the claim from the docs and from your mental model — a stated-but-unenforced invariant is worse than none, because it buys false confidence.

**5. Promote a load-bearing assumption from prose to assertion.** Grep your gate's comments and docstrings for sentences of the form "X implies Y" or "because A runs first, B is safe." Each one is an unenforced invariant. Either encode it as a check or mark it explicitly as an assumption with a known failure mode.

**6. Red-team the gate directly.** Don't ask "does the gate catch bad work?" Ask "what is the cheapest artifact that passes every check while being wrong?" Construct it. A gate you cannot defeat on paper in ten minutes is worth more than one with twice the checks.

## Test

A gate is sound when: every check either recomputes its input from the artifact under test or reads a verdict produced by an actor with no stake in the outcome; no check reads prose written by the producer about itself; every external report is parsed and branched on; unparsable or missing inputs fail closed; and every provenance token is cryptographically or structurally bound to the step that is supposed to issue it.

## Generalizes to

CI pipelines, code review checklists, release checklists, compliance attestations, agent and model-output validation, data-quality gates, and any approval workflow where the party doing the work also supplies the evidence that it was done.
