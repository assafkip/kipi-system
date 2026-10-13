---
id: same-symptom-different-root-causes-diagnose-each-failing-dep
kind: methodology
title: Same symptom, different root causes: diagnose each failing dependency separately
date: 2026-10-12
---

When several tool integrations fail with the same visible symptom (for example, 'failed to connect' at startup), do not assume they share one cause. Investigate each independently, then classify the cause.

Useful classification:
1. Environmental trigger: the configuration is correct, but a prerequisite was never set up in this particular environment (for example, an isolated runtime or dependency environment documented as first-run setup that was skipped). Signs: it works in a sibling environment and the failure is a missing file or executable. Fix by performing the setup, then verify by importing the dependencies and parsing or launching the entry point. Consider adding a startup preflight check so a skipped setup is caught early.
2. Latent defect: the configuration itself is wrong and was only working by accident or never exercised. Example: a launcher command that treats a bare script filename as a standalone script rather than as part of a project. It then resolves dependencies on its own into a separate cache and ignores the project's lockfile, silently pulling a newer major version with breaking API changes. Signs: the error is an import or API-shape error, not a missing-file error, and the installed version differs from the pinned one. Fix by invoking the tool in project mode or via an explicit entry point, so the lockfile is honored. Verify that the resolved version matches the pin.

General practices:
- Read the actual error text for each failure; identical symptoms often hide different layers (missing binary vs. closed connection after a crash).
- Compare a failing environment with a working one to separate environment drift from code or config defects.
- When a launcher shows unexpected dependency versions, check where it resolves from (lockfile vs. ad hoc cache).
- Pin and honor lockfiles in launch commands; treat major-version bumps of unpinned dependencies as a likely cause of sudden import errors.
- Surface integration failures loudly. A silently absent data source can mislead a later task that assumes it is available, so check connection status before starting work that depends on it.
- Verify each fix independently rather than assuming one fix resolved both.
