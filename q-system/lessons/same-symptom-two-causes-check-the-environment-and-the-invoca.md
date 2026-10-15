---
id: same-symptom-two-causes-check-the-environment-and-the-invoca
kind: methodology
title: Same symptom, two causes: check the environment and the invocation separately
date: 2026-10-05
---

When several services fail to start with the same symptom, do not assume one cause. Diagnose each one independently, then classify it.

Case 1, environmental: the launch config points at an interpreter or virtual environment that was never created on this machine. The setup step that builds it is documented but was never run here. Sibling machines work because someone ran it there. Fix: run the setup step, install pinned dependencies, then verify by importing the key packages and parsing the entry file.

Case 2, latent defect: the launcher was given a bare script filename. Many package runners treat a bare file argument as a standalone script and resolve its dependencies into a separate cache. That cache ignores the project's lockfile and pulls the newest major version of a dependency. A renamed class in that version then breaks the import. The pinned lockfile was correct the whole time and was never consulted.

How to apply:
- Read the actual error text for each failure. A shared symptom, such as a dropped connection, hides different causes.
- Ask whether the failure is environmental (something missing on this machine) or a latent defect (config that was always wrong but only surfaced now). Only the first is fixed by running setup.
- Check which dependency set the launcher really resolved. Compare it with the lockfile. Invoke the tool in project mode so the lockfile governs, not in script mode.
- If one machine works and another does not, diff the setup state first.
- Verify each fix on its own. Confirm the process starts and its tools register, not just that the config looks right.
- Add a startup check that fails loudly when a server is missing its runtime, so absence is never silent.
