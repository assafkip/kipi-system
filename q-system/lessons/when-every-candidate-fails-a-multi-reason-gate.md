---
id: when-every-candidate-fails-a-multi-reason-gate
kind: methodology
title: When Every Candidate Fails a Multi-Reason Gate
date: 2026-11-01
---

## When to use

An automated or semi-automated quality gate (an evaluator, reviewer model, lint-style policy check, or acceptance checklist) rejects effectively 100% of generated candidates. You are tempted to read the top rejection reason, edit the instructions or rules that produce the candidates, and re-run.

## The trap

If the gate enforces several independent criteria, a candidate must satisfy all of them at once. Rejection logs only show the reason(s) that fired first or loudest, so they describe the *current binding constraint*, not the distance to passing. Fix that one reason and the next one surfaces, with the pass count unchanged. You can burn many iterations with a monotonic 0% rate while believing you are making progress, because each round's log looks different.

## How to run the diagnosis

1. **Freeze a baseline round.** Run the gate with no changes, on a fixed input set, in a throwaway/non-committing mode. Record every rejection reason per candidate, not just the first.
2. **Change exactly one thing per round,** and keep the input set and candidate count identical. One variable per round is what makes the comparison readable.
3. **Tabulate reason counts as a distribution, not a list.** Columns: round, change under test, pass count, and a count for each distinct rejection reason. Reasons repeat across candidates; counts matter more than presence.
4. **Read the shape, not the top reason.** Interpret as follows:
   - Pass count flat while the reason mix reshuffles => you are moving the binding constraint around, not removing it. The limiting factor is upstream of the instructions.
   - One reason persists at high count through every round, immune to targeted edits => that criterion is likely unsatisfiable given the available inputs, or the criterion and the generator disagree about what evidence counts.
   - Pass count rises while total reasons fall => you are on the right variable; continue.
5. **Record non-observations explicitly.** If a category of input never appeared in any round, say so with its sample size rather than concluding it is unaffected. Zero observations is not evidence of zero effect, and writing "n = 0 of 27" prevents a later reader from inheriting a false conclusion.
6. **State the root cause as a measurement,** e.g. "no single-rule edit moved the pass count across N rounds; the rejection mix is reallocating." Avoid narrative causes you did not measure.

## How to fix once the shape is clear

- **Stop editing the rules that shape candidates.** Zero-pass with a shifting mix is a signal that the generator lacks something the gate requires, not that it was instructed poorly.
- **Check for criteria the inputs cannot satisfy.** Criteria demanding provenance, concrete figures, before/after deltas, or attributable specifics fail whenever the source material does not contain them. The fix is enriching or filtering the inputs, or routing material that lacks those attributes away from this gate.
- **Check for criteria that conflict.** Two rules can be individually reasonable and jointly impossible (one demands brevity, another demands per-item justification). Make the conflict explicit and pick a precedence order rather than tuning wording.
- **Make the gate report a full score vector,** so every criterion's status is visible on every candidate. Partial, first-failure reporting is what hides the real distance to passing.
- **Consider lowering the simultaneity requirement:** stage the gate so candidates clear criteria in sequence with repair in between, instead of needing all criteria satisfied in a single shot.

## Guardrails

- Separate the surface fix from the structural fix in your write-up, and say plainly when no surface fix shipped. A report that implies a fix landed when it did not is worse than one that names the gap.
- Keep diagnostic rounds isolated from production state: a separate working copy, scratch data, and side effects disabled. You will re-run many times.
- Report the sample size with every rate. "0 of 3, three rounds, 27 candidates" is actionable; "it keeps failing" is not.
- Set an iteration budget in advance. If the pass count has not moved after a small fixed number of single-variable rounds, escalate to the structural question instead of continuing to edit.
