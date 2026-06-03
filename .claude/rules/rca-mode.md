# RCA Mode (ENFORCED)

The diagnostic counterpart to quick-plan. Quick-plan is forward (how to build).
RCA is backward (why it broke). When a failure gets past a test, a gate, or
review, the response is a root-cause analysis written to the canonical template.

## When it fires

- A defect shipped and was caught after the fact (by a human or a gate).
- A run came back BLOCKED, or a deliverable failed validation.
- The founder says "rca this", "root cause this", "why did this break", or
  "postmortem this".
- A bug recurs after a prior fix (the prior fix treated a symptom, not the cause).

## When it does NOT fire

- A trivial bug fixed in the same breath, that never escaped a gate. Just fix it.
- A forward-looking build task. That is quick-plan or prd-os.
- A conversational question with no failure attached.

## The contract

1. Read `q-system/methodology/rca-template.md`. It is the canonical structure.
2. Write the RCA to `q-system/output/rca/rca-<slug>-<YYYY-MM-DD>.md` using every
   required section. `output/` is instance-local and gitignored.
3. Separate **surface root cause** (the trigger, what fired) from **structural
   root cause** (the latent systemic cause, why it was allowed and went uncaught).
   Multi-factor is expected, not a single tidy cause.
4. Tag each structural cause with a `type:` (code-defect, config,
   environmental-trigger, missing-test, implicit-contract, process, capacity).
5. **Verification is evidence, not assertion.** Show the command and result
   ("ran X, got Y"). A claim with no observed output is not done.
6. **Action items are checkboxes with owners**, not prose. An RCA is not finished
   until its actions are owned and trackable.
7. **Blameless.** Describe system, contract, gate, and test failures. Never name a
   person as the cause. The question is what guardrail was missing.

For prospective analysis before shipping a high-trust deliverable, use the
premortem variant in the template instead.

## Enforcement

`q-system/.q-system/scripts/rca-lint.py` validates every RCA/premortem doc on
write (PostToolUse). It checks required sections, cause-type tags, verification
evidence, checkbox action items, and blameless phrasing. Bypass a single file
with `<!-- rca-lint-skip -->` (intentional exceptions only).

## Relationship to other rules

- `quick-plan.md` — forward planning. RCA is its diagnostic mirror.
- `prd-os` — an RCA's structural fix often becomes a PRD.
- `wiring-check.md` — applies when the RCA's fix ships code/skills/hooks.
- Output the founder acts on still follows AUDHD executive-function rules.
