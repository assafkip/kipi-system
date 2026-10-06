---
id: one-symptom-two-causes-separate-environment-gaps-from-tool-i
kind: methodology
title: One symptom, two causes: separate environment gaps from tool-invocation defects
date: 2026-10-04
---

When several services fail with the same visible symptom (won't connect at startup), do not assume a shared cause. Diagnose each one on its own, and classify the cause before choosing a fix.

Case 1, environmental: the launch config points at a runtime that was never created on this machine. The setup step that builds it was documented but never run here. Another instance of the same project works because its setup did run. Fix by running the setup, then verify by importing the dependencies and parsing the entry point. Retrying or editing code would not help.

Case 2, latent defect: the launcher was invoked in a form the tool interprets differently than intended. A bare script argument was treated as a standalone script, so the tool resolved dependencies into its own cache and ignored the project's lockfile. The cache resolved a newer major version of a library in which a class had been renamed, so the import failed. The code and the lockfile were both correct. The invocation was wrong.

How to apply:
- Compare a broken environment against a working sibling first. If only one is broken, suspect missing setup.
- Read the actual error from the failing process, not the summary line from the supervisor.
- When a launcher ignores your lockfile, check how it classifies its arguments (script vs project entry point) and which dependency set it actually resolved.
- Look for a silent major-version drift whenever an unpinned resolver is in the path.
- Tag each cause as environmental or latent-defect. Environmental failures get setup or provisioning fixes. Latent defects get a change to the invocation or code, plus a test that fails under the wrong resolution.
- Verify each fix independently, by running the real startup path and not only by checking that files exist.
- Add a startup health check so a dead dependency is surfaced before real work depends on it.
