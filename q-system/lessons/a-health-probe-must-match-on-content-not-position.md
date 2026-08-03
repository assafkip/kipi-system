---
id: a-health-probe-must-match-on-content-not-position
kind: pattern
title: A health probe must match on content, not position
date: 2026-08-03
---

Applies to any liveness[PATH] check that shells out to a tool and grades its output.

**1. Ask for a sentinel, then search the whole stream for it.**
Have the probe request a fixed token in the response, and grep the entire captured output for that token. Never grade by position (`tail -1`, `head -1`, first line, last line). A subprocess commonly multiplexes its real answer with warnings, plugin/hook diagnostics, deprecation notices, and teardown logs onto one merged stream, and teardown output arrives *after* the answer by construction. Position-based matching is correct only while nothing else happens to print, which is a property of the environment, not of your code.

**2. Separate the stream you grade from the stream you log.**
Where the tool supports it, read the answer from a machine-readable channel (structured output flag, dedicated fd, output file) and let diagnostics go elsewhere. If it does not, the sentinel search in rule 1 is the fallback.

**3. One diagnosis per branch. A catch-all gets a catch-all message.**
A two-branch classifier (`matched` / `everything else`) cannot carry a specific cause on the else branch. If the failure message names a root cause, the probe must contain a test for that root cause. Structure it as: sentinel found -> healthy; known error signature found -> that specific cause; nothing matched -> `unknown failure`, plus the raw captured output and exit code. An `unknown` that prints the evidence is more useful than a confident wrong cause that sends the reader to the wrong fix.

**4. Drive the classifier with adversarial fixtures before shipping it.**
A gate that was reasoned about but never executed against hostile input is untested. Minimum fixture set, each asserting the expected classification:
- healthy answer with extra noise appended after it
- healthy answer with noise prepended
- empty output
- output containing the known error signature
- output containing an unrelated error

These are string-in/label-out tests, so they need no live dependency and cost seconds to write.

**5. Suspect environment-dependent noise.**
Output volume around a subprocess changes when plugins, hooks, wrappers, or shell init change, and when the caller runs unattended versus interactively. Treat any parse that depends on "nothing else printed" as a latent failure with a delayed trigger.

**6. Check whether the file already warns about the bug you are writing.**
If a comment near the code documents a class of misdiagnosis, read it as a spec for the code beneath it, not as background.
