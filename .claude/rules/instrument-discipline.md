---
description: Instrument discipline. A measurement is a draft until its instrument has been pointed at a case whose answer you already know. The null-claim half is held by instrument-lint.py; the rest is judgment and says so.
paths:
  - "**/investigation/**"
  - "**/output/analyses/**"
  - "**/evidence/**"
  - "**/canonical/evidence.jsonl"
---

# Instrument discipline: point the instrument at a known answer first (ENFORCED for null claims, ADVISORY elsewhere)

Read the heading narrowly. Verifying a CLAIM (citations, provenance, the evidence
ledger) has nineteen rules in this corpus. Verifying the INSTRUMENT that produced
the claim had none. This is that rule, and most of it cannot be a hook.

## The scar

case-004, 2026-09-03. Five defects in one day, one shape, each caught by a person
asking a question and none by a gate:

1. A control group written up before its DNS was checked. One lookup collapsed it.
2. A count of zero that was a property of the query set. Rerun with other query
   language: 18 instances of the thing reported absent.
3. A membership test never run against members it should exclude. `cash.app` and
   `cal.com` classified as operator-controlled hosts.
4. A corpus shaped by its seed (scam subreddits), read back as a picture of the
   world. Correcting the frame moved every count.
5. A verification command failing on a wrong path and reporting a clean zero,
   indistinguishable from a clean result.

The lesson `every-measurement-needs-a-case-whose-answer-you-already-know` existed
in the corpus the whole day. The pdftotext case (ASK-270: a token search over an
empty string returns zero matches whatever the page says) is the same shape,
filed under a chain-of-custody protocol where nobody looking for it would look.
Writing the rule a sixth time is not the fix; a rule that fires prevents the second
instance. So: one executable for the half a machine can see, and an honest label
on the half it cannot.

## The one move

Before reporting a count, a zero, or a classification, name one input whose
answer you already know and include it in the run. An input that MUST return
zero. An input that MUST hit. A row you hand-checked. A tab nothing could have
written to. If every input's answer is unknown, you are generating numbers, not
measuring.

A number with no control is a draft. Say so when reporting it, or do not report
it yet.

## What is enforced (the executable)

`q-system/.q-system/scripts/instrument-lint.py`, PostToolUse on Write/Edit in
BOTH `.claude/settings.json` and `settings-template.json`, so the fleet sync
ships the switch and not only the script. Scope: `**/investigation/findings/*.md`
and `**/output/analyses/**/*.md`; every other path exits 0 on the first check.

It blocks a file that reports a NULL-SHAPED claim (`0 of`, `Zero of`, `none
found`, `no evidence of`, `returned nothing`, `zero matches`) and carries no
CONTROL LABEL: a heading or bold label that STARTS with `Control`, `Negative
control`, `Known-answer case` or `Calibration`. A label, never bare prose, and
anchored, so `## Command and control (C2)` does not satisfy it. A zero in a
table cell is a value, not a claim, and is not matched.

A file is exempt when a date anywhere in its path is before 2026-09-04, else
when git first saw it before that date. Measured over every path in
`instance-registry.json` before it shipped: 246 in-scope files, 36 with an
uncontrolled null claim, 0 red after the exemption. The first measurement ran
over a directory that does not exist and reported zero in-scope files, which
was read as clean: scar shape 5, committed while building this. Bypass per
file: `instrument-lint-skip`. Engine test: `test_instrument_lint.py`.

## What is NOT enforced (say it, do not hide it)

- It checks a control label EXISTS, never that the control is real, ran, or
  would have caught anything. `**Control:** n/a` passes.
- Shapes 1, 3 and 4 above are not null-shaped sentences. An unchecked control
  group, an unexercised membership test and a seed-shaped corpus pass this gate
  untouched. They are judgment, and today NOTHING measures them: a trigger-eval
  fixture shipped in the first cut and was removed, because
  `skill-trigger-eval.py` runs a bare prompt from the repo root and a
  paths-scoped rule never loads there, so the fixture measured the un-ruled
  model. Captured as spillover; until the harness can seed a matching path, the
  judgment half is stated, not measured.
- A null result reported in chat and never written to a file is invisible to a
  PostToolUse hook, the same blindness `plan-lint.py` states for a plan that was
  skipped.

## The tell

When a result is surprising, suspect the harness before the subject. Four of the
five case-004 numbers were plausible and alarming, and in every case the
instrument was wrong and the world was fine. Print one flagged row in full before
believing the aggregate.

## Cross-references

`evidence-ledger.md` (claim discipline; this is its instrument-side sibling) ·
`skill-hook-pairing.md` (why the judgment half stays interpretive) ·
`quick-plan.md` (plan-lint, the precedent for scope-first and date grandfathering)

<!-- enforcement -->
```json
[
  {
    "clause": "Instrument discipline: point the instrument at a known answer first",
    "status": "ENFORCED",
    "exec": "q-system/.q-system/scripts/instrument-lint.py",
    "config": ".claude/settings.json",
    "test": "q-system/.q-system/scripts/test_instrument_lint.py",
    "note": "ENFORCED covers the null-claim label check only (shapes 2 and 5). Shapes 1, 3, 4 are judgment with no measurement today: skill-trigger-eval.py cannot load a paths-scoped rule (spillover captured).",
    "directives": 9
  }
]
```
