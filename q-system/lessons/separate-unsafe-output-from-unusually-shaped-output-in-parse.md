---
id: separate-unsafe-output-from-unusually-shaped-output-in-parse
kind: pattern
title: Separate unsafe output from unusually shaped output in parsers
date: 2026-10-05
---

When a parser sits between a nondeterministic producer (such as an LLM) and a downstream consumer, give every check an explicit severity class. Do not let each check default to refusing the whole run.

The failure mode: every validation in the parse layer was a whole-run refusal. Nothing distinguished "this output is unsafe" from "this output is shaped unusually." Two kinds of rule ended up with equal power:
- Rules that protect something, because a violation would reach a sink and cause harm.
- Rules that only describe an expected shape, where a violation changes nothing downstream.

A formatting rule on text that can never reach the consumed field had the same blast radius as a safety rule. A count limit whose own comment said real input could not reach it behaved the same way. The run stopped on shape twice, from two different checks.

How to apply it:
- For each check, name the sink it protects. If the rejected content cannot reach any sink, the check is cosmetic. Drop it, or have it normalise the output and log.
- Give each check one of three outcomes: refuse the whole run (unsafe), drop or repair the offending item and continue (malformed but containable), or warn and continue (unusual but harmless).
- Reserve whole-run refusal for violations that would cause real harm if passed through.
- Scope each rejection to the smallest unit that contains it, such as one item in a batch, not the batch.
- When a limit is set by assertion, check it against real production-shaped input before shipping. A comment saying a bound is unreachable is a claim, so test it.

Test the parser with the shapes the producer actually returns, not just the shapes the spec describes. Collect real outputs, including fenced, prefixed, trailing-text, oversized and partial ones. Run each through the parser as fixtures. Add a case per check showing which outcome class it lands in. A contract that is all-or-nothing on a nondeterministic producer will fail repeatedly on benign variation, so the parser's strictness should track the harm of the violation and not the surprise of the shape.
