# Numbers come from a script, never from the model (ENFORCED, founder-directed 2026-09-08)

Founder, verbatim: *"I can't think of a reason I would need you to do arithmetic
when I can allocate calculations to a python script."*

Any number that reaches the founder, a client, a canonical file or a commit
message is produced by a command whose output is pasted, never by the model
computing it. Counts, rates, percentages, ratios, lifts, sums, medians, and any
comparison between two of those.

## The rule

Write the script. Run it. Paste what it printed.

If a number appears in your output and you cannot name the command that printed
it in this session, it is not a number yet. Delete it or go run something.

## Why this is a rule and not advice

2026-09-08, one session, three wrong numbers from the same defect:

- Four telemetry columns reported dead because they read zero in a file that
  structurally cannot contain a row any entry control stopped. Wrong population.
- `psAIResponseFail` reported as firing on zero of 2.29M rows. The column is
  blank on 74.8% and 79.2% of rows, so the denominators were 4x and 4.8x too
  large. Written in the sentence recommending the founder raise it with the
  client, in the document that had just corrected the previous error.
- A bench output of `0.00%` relayed to the founder as proof the tool worked. It
  was `resolve()` failing to find a key: 106 of 121 columns unreachable, so every
  dotted rule measured zero. A false green with a denominator attached.

The counting reproduced to the row every time. The arithmetic was never the
defect. The population was, and a model cannot see a population it did not
enumerate.

Same class, older and more expensive: the April JA3 finding generalised from a
curated 500-good / 500-bad sample to the whole platform. The two fingerprints it
named as anti-detect signatures are 54% of PureSpectrum's traffic, and the larger
one rejects below baseline. That document reached the client.

## What a script gives you that a model does not

- It names its input file, and re-running it tomorrow gives the same answer.
- It cannot skip a row it did not think of.
- It fails loudly on a missing column instead of returning a plausible zero.
- Its denominator is visible in the code rather than assumed in a sentence.

## The deterministic backstop, and its honest scope

One instance has a coded backstop: the Pure Spectrum threat-intel package holds
a `rates.py` that refuses to compute a rate without its population, its blank
count and what it excludes, plus a test that enumerates `src/` from the
filesystem and fails on rate-shaped arithmetic written outside it. Built
2026-09-08, 1062 tests green in a detached checkout. Port it where a package
computes rates that reach a client; do not assume it exists here.

**A guard like that covers one package's `src/`. It does not cover prose.** All three
errors above were in markdown and chat, where no hook can see them. This rule is
the half no script can enforce, which is why it is written down: it loads at
session start and the discipline has to hold in the writing.

## Does not apply

- A number quoted from a source with a citation, where the source did the arithmetic.
- Trivial restatement of two figures that were both printed.

## Cross references

`token-discipline.md` (verification loops), `instrument-discipline.md` (a null-shaped
claim needs a control), `q-system/methodology/anti-hallucination.md`.
