---
id: a-check-with-no-caller-is-not-a-check
kind: methodology
title: A check with no caller is not a check
date: 2026-08-03
---

Symptom: a validator, linter, guard, or audit script is written, reviewed, and correct. Run by hand it detects the problem and exits non-zero. Nothing ever runs it. The defect it was built to catch keeps shipping, and the team believes it is covered.

Why it happens: authoring the mechanism feels like the hard part, so completion gets declared there. Registration in the runner is treated as bookkeeping to do later, and later never arrives. The failure repeats because nothing in the process distinguishes 'the check exists' from 'the check runs'.

How to work this way:

1. Treat a new check as unfinished until you can name its invoker. Before writing a line of the check, decide which existing entry point will call it: the pre-commit stage, the CI job, the release pipeline, the setup/update routine, the test suite. If no entry point fits, that is the first thing to build.

2. Prove the wiring by observation, not by grep. Grepping that the name appears somewhere in the repo proves the string exists, not that the running system loads it. The evidence is: trigger the entry point on a deliberately broken input and watch it fail. Then fix the input and watch it pass. A check that has never blocked anything has never been proven to block.

3. Add a negative test at the wiring layer, not only the logic layer. Unit tests of the check's logic pass whether or not anything calls it. The test that catches this class asserts the pipeline itself fails when a violating file is present.

4. Make undeclared assets fail loudly. Keep a manifest of every check the system claims to run, and have a meta-check compare the declared set against what is actually present and actually invoked. Present-but-undeclared and declared-but-uninvoked are both errors. This is the only defense that scales past human memory.

5. Do not stop at one instance. If you find one unwired check, sweep for the rest immediately. This defect arrives in clusters, because it comes from a habit rather than an oversight. Look at everything added in the same period by the same process.

6. Read your own tooling's warnings as findings. When routine output reports something present-but-undeclared or unreferenced, that line is the bug report. Noise-blindness to your own diagnostics is how this survives in plain sight.

The test that separates a real gate from decoration: can you point at a run, on a shared pipeline rather than your machine, where this check failed the build and someone had to respond? If not, you have written a tool, not installed a gate.
