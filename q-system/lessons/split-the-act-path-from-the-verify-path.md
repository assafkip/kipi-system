---
id: split-the-act-path-from-the-verify-path
kind: pattern
title: Split the act path from the verify path
date: 2026-07-27
---

When an automated step both performs an action and confirms it worked, check which underlying capability each half depends on. If the same capability powers both, a single outage takes out the whole step and the loop cannot tell success from failure.

How to apply:

1. For every step in an automated flow, write down two things: the capability used to ACT, and the capability used to VERIFY. Same entry twice is a defect, not a coincidence.

2. Give verification at least one fallback that reads through a different channel. If the primary check is visual/rendered capture, add a structured/state read (query the underlying data, the API, the DOM, the log, the exit code). If the primary is structured, keep a capture as backup.

3. Prefer the machine-readable channel as primary and the rendered one as fallback. Rendered checks are heavier, flakier, and usually the first thing to break.

4. Watch for a fallback that quietly re-imports the failed dependency. A common shape: the stable locator is flaky, so someone works around it by deriving a position from a rendered capture. That silently chains the action path onto the verification capability, and one outage now kills both. Fix the flaky locator (better resolution, retry with a different locator strategy, wait-for-stable) instead of routing around it through the other capability.

5. Preflight both capabilities at run start with a cheap probe. Fail before the irreversible action, not halfway through it, and name which capability failed.

6. Make the failure loud. If verification cannot run, the step halts with an explicit unverified state. Never let it proceed and report success on the strength of the action having been attempted.

7. Test it by disabling the capability on purpose. Assert the run either takes the fallback path or stops with a named reason. A verification method that has never been observed failing over is an assumption, not a fallback.
