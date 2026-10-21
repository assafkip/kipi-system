---
id: same-symptom-different-root-causes-diagnose-each-failing-dep
kind: methodology
title: Same symptom, different root causes: diagnose each failing dependency separately
date: 2026-10-19
---

When several tools or services fail with the same visible symptom (for example, all refuse to connect at startup), do not assume one shared cause. Triage each failure on its own and classify it.

1. Environmental trigger: the configuration is correct, but a prerequisite step was never performed in this particular environment, such as a missing virtual environment, an uninstalled dependency, or a skipped first-run setup. Clue: an otherwise identical sibling environment works. Fix by performing the documented setup, then confirm that imports succeed and the entrypoint parses.

2. Latent defect: the configuration itself is subtly wrong and was only working by luck or was never exercised. Example: a launcher treats a bare file argument as a standalone script rather than as part of a project, so it resolves dependencies in its own cache and ignores the project's lockfile. It then pulls a newer major version with a renamed or removed API, producing an import error. Fix by invoking the tool in project mode so the lockfile is honored, or by explicitly running the entrypoint through the project's pinned environment.

Practical checks:
- Compare a broken environment against a working one to separate environmental causes from code or config causes.
- Read the actual error from running the command by hand, not just the summarized connection status. 'Connection closed' usually hides a crash on import.
- Look for a mismatch between the versions pinned in the lockfile and the versions actually resolved at runtime.
- Verify the fix by reproducing the original failure path: start the server the same way the client does, not just by importing packages.
- Surface startup health notices before starting work that depends on these tools, since a silent absence of capabilities can invalidate results without any error.
- Make first-run setup a checked step, such as a script or startup check, rather than documentation that relies on someone remembering it.
