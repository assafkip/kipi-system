---
id: assert-on-the-artifact-not-just-the-machinery
kind: pattern
title: Assert on the artifact, not just the machinery
date: 2026-07-06
---

When a deterministic computation feeds into a final assembled output, its absence must be impossible to miss. Two failure shapes combine into a silent, wrong result:

1. Fail-open assembly. A broad `catch`/`except` around the computation swallows any error and substitutes an empty or default value. The pipeline keeps running and produces something that looks complete. Worse, if a softer, judgment-based layer (a narration step, a fallback estimate, a sampled approximation) sits downstream, it fills the vacuum the missing layer left — so the gap is not just hidden, it is actively papered over with plausible content.

2. Gates that test the mechanism, not the outcome. Every check verifies that the computation is correct WHEN IT RUNS: coverage, correctness, edge cases. None asserts that it actually ran in the shipped artifact. A silent swallow lives in the space between 'the code is correct' and 'the output contains the code's result.'

How to avoid it:
- Never catch broadly around a required computation and continue with a default. If a mandatory layer cannot produce its value, the output is invalid — fail loud, or stamp the artifact as incomplete. Silence plus a default is the trap.
- Distinguish 'absent because there is genuinely nothing' from 'absent because something threw.' Empty input and swallowed exception must produce different, visible states.
- Put one check on the final artifact that asserts the required layer is present in it, not just that the layer's code passes in isolation. 'The engine works' and 'the engine's output reached the deliverable' are separate claims needing separate proofs.
- When a soft/generative layer can substitute for a hard/deterministic one, make substitution observable. The output should reveal which layer produced each part, so a downstream reader (or gate) can catch narration standing in for a determination.
- Treat a required-value pipeline as fail-closed by default: absence blocks or flags; presence is proven on the artifact, not assumed from green unit checks.
