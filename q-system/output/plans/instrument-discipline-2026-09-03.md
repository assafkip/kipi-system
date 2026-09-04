# Instrument discipline: evaluation before build

Status: EVALUATION. No code written. Founder redirect point.

## What/why

Five case-004 defects in one day, all one shape: a measurement whose instrument was
never pointed at a case with a known answer. The lesson exists (twice). The brief
asks whether this is an arrival or an enforcement problem, and which of three
candidates (A ledger field, B findings lint, C generalized rule) fits kipi.

## Diagnosis (measured 2026-09-03, read-only)

**Arrival is broken in Alice, concretely, and it is a sync gap, not a design gap.**

- The lesson body delivery mechanism is `lessons-inject.py` (UserPromptSubmit,
  shipped to skeleton 2026-08-29, commit 229a5fc9, on origin/main).
- Alice has NEITHER the script nor the wiring: `lessons-inject` appears 0 times in
  Alice's `.claude/settings.json`; the script is absent from
  `q-system/.q-system/scripts/`. Alice's scripts dir last synced 2026-08-30 19:00,
  yet the file is missing, so the sync that ran did not carry it.
- What Alice DOES get is SessionStart titles only. The lessons-inject docstring
  records that title-only injection was measured as non-delivery. So in Alice the
  lesson is on disk, listed by title, and never read. That is the arrival defect,
  and it is the same defect the skeleton already fixed six days ago.

**Enforcement has a real hole, but not where candidate A aims.**

- Alice's evidence ledger has 6 rows, all case-002, dated 2026-08-26/27.
  Case-004 (2026-09-03, the day of the five defects) wrote ZERO ledger rows.
  The ledger was not in the loop. A gate on the ledger gates an empty pipe.
- The five defects all live in findings and analysis prose
  (`FINDING-commerce-corpus-2026-09-03.md` holds the cash.app/cal.com
  misclassification). The prose is the artifact; no findings-level gate reads a
  null-shaped claim.
- Alice already has an instance-local findings hook,
  `q-investigate/skills/osint/scripts/findings-verify-hook.py`, and it is wired
  0 times in settings.json. Its own header says settings.json is "safe" from
  sync, which is exactly why it arrived dead. Second arrival scar, same shape.

**Stated so it is not smuggled:** 19-vs-2 in rule prose is true, but prose count
is not the lever. The lever is (1) a body-delivery hook Alice does not have and
(2) a findings gate nobody has.

## Approach: candidate verdicts

**A. Ledger `control` field. REJECT.**
Fights the ledger's contract in a subtle way: the contract is "a command and its
output", both things a machine can check exist. "Control" is a judgment (what is a
known-answer case for this measurement?), and a required free-text field gets
filled with "n/a", which is the decoration failure. And it gates a pipe case-004
never used (0 rows). Captured instead as spillover: the investigation flow should
write ledger rows at all. That is a separate issue.

**B. Findings lint. BUILD, modeled on plan-lint.py.** The deterministic slice.
Fits rule-plus-paired-hook exactly; scope-test-first; honest boundary; date-in-
filename grandfathering with precedent.

- Scope: `**/investigation/findings/*.md` and `**/output/analyses/**/*.md`.
  Everything else exits 0 on the first check. Most instances have neither path,
  so fleet blast radius is the q-investigate instances only.
- Trigger: a null-shaped claim line (`0 of`, `none found`, `no evidence of`,
  `returned nothing`, `zero matches|results|hits`, `no instances|matches|results`).
- Passes when the file carries a control LABEL (heading or bold-run, same
  label-not-prose rule as plan-lint): `## Control`, `**Control:**`,
  `**Negative control:**`, `**Known-answer case:**`. Label, never bare prose, so
  the word "control" in a sentence cannot satisfy it.
- Grandfather: filename date before 2026-09-04 is exempt. Measured population:
  10 of 55 findings/analysis files in Alice carry a null-shaped line; 5 files
  already carry a control-ish label. Without the cutoff the gate is red on its
  own population and gets switched off.
- Bypass: `instrument-lint-skip` in the file.
- HONEST BOUNDARY (in the docstring): checks a control label EXISTS, never that
  the control is real, ran, or would have caught anything. Cannot see a null
  result the model reported in chat and never wrote down. Cannot see defects 1, 3
  and 4 (control-group DNS, membership test, seed-shaped corpus): none of those
  are null-shaped sentences. It catches defect shapes 2 and 5 only. Say so.
- Lands: `q-system/.q-system/scripts/instrument-lint.py` + `test_instrument_lint.py`,
  wired PostToolUse(Write|Edit|MultiEdit) in BOTH `.claude/settings.json` and
  `settings-template.json` (settings-template-sync-check holds this).

**C. Generalized rule plus trigger-eval fixture. BUILD, as a NEW skeleton rule.**
`evidence-capture-protocol.md` is Alice-local (one of 3 rules Alice has that the
skeleton does not); editing it reaches one instance. So: new
`.claude/rules/instrument-discipline.md` in the skeleton (propagates), stating
the principle once, listing the five case-004 shapes and the pdftotext ASK-270
case beneath it as incidents, naming `instrument-lint.py` as its executable so
ENFORCED is honest, and stating plainly that shapes 1, 3, 4 are judgment with no
hook. Fixture `q-system/.q-system/skill-evals/instrument-discipline.json` for the
judgment half: prompts where the model SHOULD name a control before reporting a
count. Advisory, on-demand, same posture as the other five fixtures.

## Files to touch

- `q-system/.q-system/scripts/instrument-lint.py` (new, stdlib, plan-lint shape)
- `q-system/.q-system/scripts/test_instrument_lint.py` (new; a red case per
  trigger phrase, a label-vs-prose case, a grandfather case, an out-of-scope case)
- `.claude/settings.json` and `settings-template.json` (one PostToolUse entry each)
- `.claude/rules/instrument-discipline.md` (new)
- `q-system/.q-system/skill-evals/instrument-discipline.json` (new)
- `.prd-os/spillover.jsonl` via `prd_runner.py spillover add` for: (1) Alice missing
  lessons-inject, (2) investigation flow writes no ledger rows, (3) Alice's
  findings-verify-hook.py wired nowhere

## Acceptance criteria

- [ ] `python3 test_instrument_lint.py` green, and one mutation (delete the
      null-claim regex) makes it red
- [ ] Hook fed the real `FINDING-commerce-corpus-2026-09-03.md` under a
      post-cutoff filename exits 2; under its real filename exits 0 (grandfather)
- [ ] `grep -c instrument-lint .claude/settings.json settings-template.json` = 1 each
- [ ] settings-template-sync-check passes
- [ ] the skeleton dry-run from main shows the script + rule reaching Alice.
      Today it ABORTS: skeleton HEAD is on fix/candidate-draft-one-definition,
      so nothing propagates until this lands on main. PR to main first, then
      dry, then apply.
- [ ] Three spillover items captured

## Patterns to follow

- `plan-lint.py`: scope-first, label-not-prose, CUTOFF by filename date, three
  stated boundaries, `-skip` marker, stdin JSON, exit 0/2.
- `skill-trigger-eval.py` fixture shape for the judgment half.
- `evidence-ledger.md` honest-boundary table convention for the rule text.

## What NOT to build

- No Stop hook scanning chat for null claims: same cheapest-compliance failure
  lessons-inject's docstring measured (the model stops writing the sentence).
- No ledger field. No edit to Alice-local rules from the skeleton.
- Shapes 1, 3, 4 get no hook. They are measured by the on-demand fixture run
  through `skill-trigger-eval.py`, a signal, never a pass/fail check.
