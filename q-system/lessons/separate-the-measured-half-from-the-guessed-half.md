---
id: separate-the-measured-half-from-the-guessed-half
kind: methodology
title: Separate the measured half from the guessed half
date: 2026-09-07
---

## The shape

You observe something real and countable: a count, a failed run, a file in the wrong place. You reach for the cause that fits, write observation and cause into the same sentence, and ship it as a comment, a commit message, a finding, or a ticket. The observation was measured. The cause never was. Because the number is right, every later reader treats the clause beside it as measured too, and the guess becomes settled history that nobody re-derives.

This survives review because the two halves get read as one claim. A reviewer checks the verifiable half, it holds, and the causal half rides through as a subordinate clause. A clause carries no command and no output, so nothing about it can fail.

## How to write it

Split every such sentence in two before you commit it.

1. State the observation with the command or query that produced it, and its output.
2. State the cause on its own line, prefixed with its evidence class: MEASURED (with the check that produced it) or HYPOTHESIS (untested).
3. If it is a hypothesis, write the check that would distinguish it from the next most likely cause. Either run that check now, or leave it written down as the next step.

A cause with no named check beside it is a hypothesis regardless of how confident it feels.

## The cheapest discriminating check

Before accepting a cause, ask what the world would look like if it were false, then look for exactly that.

- Cause claims a timing relationship. Compare the two timestamps directly. A single ordering comparison kills or confirms it.
- Cause blames a specific line, branch, or setting. Remove or neutralize it in a scratch copy and reproduce. If the behavior is unchanged, that line is not the mechanism, no matter how well it reads.
- Cause blames an external dependency's state. Query that state rather than inferring it from an error message.

These checks are usually minutes. The cost of skipping them is that a wrong mechanism gets cited by later work as an established fact.

## Two failure modes to expect

**Independent readers converge on the same wrong cause.** Agreement between two reviewers is not evidence when both read the same code and neither ran anything. Convergence measures shared priors, not truth. Treat a repeated cause as confirmed only when someone executed a check that could have contradicted it.

**One true cause hides another.** Fixing the first confirmed cause can reveal a second, unrelated one underneath. Do not close on the first fix that changes the symptom. Re-run the original observation after the fix and confirm the number moved to where the cause predicts, not merely that it moved.

## When it does not apply

A cause you already proved in this session with a check that could have failed is measured, and writing it plainly is correct. The rule targets the cause you inferred, not the one you tested.
