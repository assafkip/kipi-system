---
id: grade-each-output-check-by-what-it-protects-not-by-whether-i
kind: pattern
title: Grade each output check by what it protects, not by whether it failed
date: 2026-09-14
---

## The failure shape

A pipeline consumes output from a nondeterministic producer, such as a language model, and runs it through a parse or validation layer. Every check in that layer has the same power: any failure refuses the whole run. Nothing in the design separates "this output is unsafe" from "this output is shaped unusually."

This causes two problems:

- Checks that protect nothing carry the same weight as checks that do. One example is a rule against text outside the structured payload, when that text can never reach the field that gets used. Another is a count cap whose own comment says real input cannot reach it. Either one can stop the run.
- The producer is nondeterministic, so harmless variation in shape will come up sooner or later. An all-or-nothing contract means one harmless variation throws away a whole run of good work.

## How to apply

1. List every check in the parse layer. For each one, write down the specific bad outcome it prevents. If you cannot name one, the check is cosmetic.
2. Put each check in one of three tiers:
   - **Refuse the run:** the output could cause harm if used, for example unsafe content or a field that would carry wrong data downstream.
   - **Drop the item:** one record is malformed but the others are independent. Skip it, log it, keep the rest.
   - **Normalize or tolerate:** the shape is unusual but meaning is intact, for example wrapper text around the payload or extra whitespace. Strip it or ignore it and record that you did.
3. Tie each refusal to the property it protects, not to the nearest structural proxy. "Payload is not the only text in the response" is a proxy. "The field we publish contains something other than the payload" is the property.
4. Treat any numeric limit as a claim about real data. Before you ship a cap, measure it against live producer output. A comment saying real data cannot reach a limit is a hypothesis, not a measurement.
5. When the same kind of producer has already broken an all-or-nothing contract once, assume the whole class is fragile. Audit every strict check at once instead of fixing only the one that fired.

## The test gap that hides it

Fixtures written by hand encode the shape the author expects, so every strict check passes. The fix is to build the parser's test set from outputs the producer actually returned: fenced payloads, leading prose, trailing commentary, empty lists, over-long lists. For each one, assert which tier it lands in. Also include at least one input that should refuse the run, and confirm it does. A tolerance layer with no refusing case can quietly turn into accept-everything.

## Signal to watch for

If a run was refused and the output was fine when a person read it, that is a check in the wrong tier. Re-grade that check. Loosening the whole layer is the wrong fix.
