---
id: separate-unsafe-output-from-unusually-shaped-output-in-parse
kind: pattern
title: Separate unsafe output from unusually shaped output in parsers of nondeterministic producers
date: 2026-10-04
---

When a parser sits behind a nondeterministic producer such as an LLM, give every check one of two classes and make the class explicit in code.

1. Safety checks. They protect something downstream: a field that must never carry untrusted text, a size limit that guards a destination, a value that must match an allowlist. A failure refuses the output, and often the whole run.
2. Shape checks. They only complain that the output looks unusual: extra text around the payload, an unexpected item count, a wrapper the producer added. A failure normalizes, truncates, drops the offending item, or records a warning. It does not stop the run.

The failure mode is a parse layer where every check is a whole-run refusal. Nothing distinguishes 'this is unsafe' from 'this is shaped oddly', so a rule that protects nothing has the same power to kill a run as a rule that protects something.

Two audit questions for each check:
- What downstream harm does this prevent? If the answer is 'none, the offending part can never reach the sink', the check is a shape check. Demote it or delete it.
- Is a numeric cap backed by evidence? A comment saying 'a real input cannot reach this' is a claim, not a measurement. Check the cap against real production inputs, and set it above the observed maximum with headroom.

Tests to ship with the parser:
- Feed it the shapes the producer actually returns, captured from real runs: fenced output, prose before and after the payload, trailing commentary, empty and oversized lists, duplicate items.
- Assert that shape deviations degrade gracefully and that safety violations still refuse.
- Add a case that replays a real worst-case input through the cap.

This is the same defect as any all-or-nothing contract placed on a nondeterministic source. Strictness belongs where it buys safety. Everywhere else, tolerate and normalize.
