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
ships the switch and not only the script. Scope, WIDENED 2026-09-21: any `.md`
under `/investigation/findings/`, `/output/analyses/`, or any `/output/`
directory. Every other path still exits 0 on the first check.

It blocks a file that reports a NULL-SHAPED claim (`0 of`, `Zero of`, `none
found`, `no evidence of`, `returned nothing`, `zero matches`) and carries no
CONTROL LABEL: a heading or bold label that STARTS with `Control`, `Negative
control`, `Known-answer case` or `Calibration`. A label, never bare prose, and
anchored, so `## Command and control (C2)` does not satisfy it. A zero in a
table cell is a value, not a claim, and is not matched.

A file is exempt when the date in its BASENAME is before ITS SCOPE's cutoff,
else when git most recently added it before that date. A directory date never
counts. Each scope carries its own cutoff, set on the day that scope was added,
and where two scopes overlap the EARLIEST wins, so a widening can only add files
and can never quietly exempt one the older scope already covered. Original two
scopes, cutoff 2026-09-04, measured over every path in
`instance-registry.json` before it shipped: 246 in-scope files, 36 with an
uncontrolled null claim, 0 red after the exemption. The first measurement ran
over a directory that does not exist and reported zero in-scope files, which
was read as clean: scar shape 5, committed while building this. Bypass per
file: `instrument-lint-skip`. Engine test: `test_instrument_lint.py`.
## Why it guards `/output/` now, and what it refused (measured 2026-09-21)

The first cut guarded two directories. That is this rule's own failure wearing
this rule's clothes: the mechanism was scoped to the room it was built in. Three
wrong numbers reported on 2026-09-20 were every one null-shaped, and the one of
the three that reached a FILE landed outside those two directories. The other two
were spoken and never written, which this widening does not touch and the boundary
section below states plainly. Read the claim at that size: the scope moved because
a written null claim could land in a directory nobody was watching, not because
widening a file scope could have caught a number said out loud. Blast radius
measured with the CURRENT
logic BEFORE the tuple moved, over every path in `instance-registry.json`:

| candidate | `.md` files | uncontrolled null claim | red under a 2026-09-21 cutoff |
|---|---|---|---|
| `/output/` (picked) | 7697 | 522 | 3 |
| `/output/rca/` | 381 | 68 | 0 |
| `/output/plans/` | 2775 | 96 | 0 |
| `/investigation/` | 5287 | 149 | 37 (refused) |
| `/memory/` | 614 | 10 here, 12 in auto-memory | 12 (refused) |

`/output/` is the widest candidate that is nearly green, so it took the whole
directory rather than the two subdirectories that were proposed. The three still
red are dated after the cutoff or are untracked AND undated, so no exemption can
reach them; they block on their next edit and that is the gate working.

**Refused, with the number as the reason, not an opinion.** `/investigation/`
keeps 37 red under any cutoff: they are scraped evidence `content.md` files
("OCR ... returned 0 characters"), undated and untracked, so the exemption
structurally cannot fire and they stay red forever. `/investigation/findings/`
remains in scope, which is the half of investigation that reports rather than
captures. `/memory/` is refused because the path fragment cannot tell an
instance `memory/` (0 red) from `~/.claude/projects/*/memory/` (12 red, also
undated and untracked), and that is the highest-traffic write path in the
system. A gate red on its own population on day one gets switched off, and a
gate that is off protects nothing.

**One half of the widening did not land and is not pretended to have.** This
file's `paths:` frontmatter still names `**/output/analyses/**`, not `**/output/**`,
because `apply_claude_changes.py` refuses ANY frontmatter change by ANY op: the
keys that decide whether a rule loads are out of that tool's reach by design. So
the GATE fires on every `/output/` write fleet-wide while this INSTRUCTION still
loads only on the older paths. The gate's stderr carries the full fix, so a
blocked write teaches without the rule in context. Widening the frontmatter is a
separate change through a different door.


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
- **A null result reported in chat and never written to a file is invisible, and
  a wider scope does not narrow that hole by one inch.** Read the 2026-09-21
  widening exactly as narrow as it is: it covers more FILES, never more CLAIMS.
  This is where most of 2026-09-20's wrong numbers lived. "6 gates wired, 100%
  have a red case" (a regex that could not resolve 60 of 62 paths), "0 of 0
  known-need files ranked" (a control set that resolved empty while the script
  printed a ranking header and exited 0), and a Jev run whose 61 calls all
  returned HTTP 422 while the script printed clean empty results and exited 0
  were every one SAID OUT LOUD, and two of the three never reached a file at
  all. A PostToolUse hook sees the file that was written, never the claim that
  was spoken, the same blindness `plan-lint.py` states for a plan that was
  skipped. What catches a spoken zero is the one move above, and it is judgment.
- **An undated AND untracked file can never be exempt.** That is the price of a
  self-maintaining exemption over a hand-kept list, and it is why the widened
  scope left 3 files red rather than 0.

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
    "note": "ENFORCED covers the null-claim label check only (shapes 2 and 5), and only on FILES. Shapes 1, 3, 4 are judgment with no measurement today: skill-trigger-eval.py cannot load a paths-scoped rule (spillover captured). Scope widened 2026-09-21 from two directories to any /output/ directory, measured at 3 of 7697 red before the change; /investigation/ (37 red, unexemptable) and /memory/ (12 red in auto-memory) were refused on their own numbers. The paths: frontmatter was NOT widened, because apply_claude_changes.py refuses every frontmatter change by design. A claim spoken and never written stays invisible at any scope.",
    "directives": 16
  }
]
```
