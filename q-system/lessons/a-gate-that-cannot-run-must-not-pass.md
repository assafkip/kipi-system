---
id: a-gate-that-cannot-run-must-not-pass
kind: pattern
title: A gate that cannot run must not pass
date: 2026-08-17
---

When an automated check wraps its own logic in a broad try/except and degrades to "warn" on any exception, it stops being a gate. Anything that breaks the checker now guarantees the artifact ships. Apply this when building or auditing any validation step that stands between generated content and a publish, deploy, or send action.

**Split the failure classes at the handler.**
Two different things get caught by one bare except: the environment failed (external service down, dependency unreachable, credentials expired) and your own code failed (missing attribute, renamed function, changed signature, import error). Only the first is a defensible reason to continue with a warning. The second is a defect and must block. Catch the specific exception types the environment produces; let every other exception propagate and fail the gate closed.

**Narrow the try to the line that can legitimately fail.**
Moving one safe lookup outside the try while leaving the actual call inside protects nothing. Ask which single statement touches the untrusted boundary, and wrap only that.

**Make the error text name the layer that broke.**
A wrapping handler attributes every failure to the subsystem it wraps, so a bug in the caller reads as a bug in the callee and the next investigator starts in the wrong file. Include the real exception type and origin in the degraded-mode message.

**Write the negative test that breaks the checker.**
For each gate, add a test that removes or renames the symbol the gate depends on and asserts the gate blocks rather than warns. If that test cannot go red for the reason you care about, the gate is unverified.

**Wire the suite into the publisher, not into a dashboard.**
A test suite that has been failing for days while a scheduled job keeps publishing is decoration. The automated path that produces outward-facing output should refuse to run when the gate suite is red. Consumption is what makes a test a control.

**Fix at the source of truth, not in a synced tree.**
If a directory is a destination for a sync, vendoring step, or code generator, a fix landed there is reverted on the next run. The tell is a commit history containing more than one "restore the thing the sync deleted." When you see that shape, stop restoring the downstream copy and move the change upstream, or the same outage returns on the next sync.

**The diagnostic, in one question:** for every guard between generated content and the outside world, what does it do when its own dependency is broken? If the answer is "passes," you have a publisher with a comment about safety attached.
