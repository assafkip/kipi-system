---
id: a-health-check-must-match-content-not-position
kind: pattern
title: A health check must match content, not position
date: 2026-08-10
---

When a check shells out to another program and decides pass/fail from its output, two failures ride together: reading the wrong part of the stream, and naming a cause the read never tested.

**How to write the read**

- Match on the string that proves success, anywhere in the output. Never take a fixed position (last line, first line, Nth field) as the answer. Any process that merges the payload with diagnostics onto one stream can print teardown noise after the payload; plugins, hooks, deprecation warnings and telemetry all emit at exit. A positional read is only correct while nothing else happens to print, which is a property of today's environment, not of the code.
- If the tool offers a structured output mode (JSON, an exit code that distinguishes cause classes, a separate stream for diagnostics), take it and parse the field. Ask for a machine-readable answer instead of scraping a human-readable one.
- Where output must be scraped, read the whole stream and search it; strip known noise explicitly rather than assuming its absence.

**How to write the failure message**

- A branch may only assert a cause the probe actually tested. If the check looks for one success token, its negative branch means "success token absent" and nothing more. Label it that way.
- Never let a catch-all `else` carry a specific diagnosis. Logged out, answered fine but printed extra, network dropped, binary missing, and timed out are distinct states; one branch collapses them into whichever guess the author wrote, and the alert then points the reader at the wrong fix. A wrong diagnosis costs more than no diagnosis, because it directs the search away from the cause.
- Give the catch-all branch a generic label plus the raw evidence: what was searched for, and the captured output (truncated). If specific causes matter operationally, probe for each one separately.

**How to prove it**

- Drive the classifier directly with adversarial fixtures rather than reasoning about it: valid answer with trailing noise, valid answer with leading noise, empty output, error text only, timeout, and the genuine failure the message claims. Feed strings to a pure function; no live dependency needed.
- A check with no such test has been reasoned about, not executed. That is where the positional read survives: it passes every hand-run because the hand-run environment is quiet.

**Where this bites hardest**

Gates in unattended jobs. A wrong verdict there halts real work and sends whoever reads the alert down a false trail, and the noise that broke it can arrive from an unrelated dependency update with no change to the checking code at all. Treat a comment warning about a failure class as a signal that the class is live in this code path, and make the code below it satisfy the warning rather than restate it.
