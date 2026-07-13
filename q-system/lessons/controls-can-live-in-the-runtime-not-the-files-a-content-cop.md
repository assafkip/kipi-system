---
id: controls-can-live-in-the-runtime-not-the-files-a-content-cop
kind: methodology
title: Controls can live in the runtime, not the files; a content copy does not port enforcement
date: 2026-07-13
---

When behavior on one surface seems well-controlled, identify the actual control mechanism before assuming it travels with the code. Controls often live in the runtime architecture: which configuration sources the process loads, whether hooks fire on each action, whether a human is synchronously in the loop. A different execution surface (a background agent, an SDK-embedded session, a scheduled job) can be constructed to load none of those sources, so every file-based rule is absent by construction no matter how faithfully the files were copied.

How to apply:

1. Before porting or trusting a control, trace the enforcement path end-to-end: what code loads the rule, on which surface, and what happens on the surface where the workload actually runs. Read the runtime's option flags (settings sources, permission modes) rather than inferring from the presence of config files.

2. When porting a system, scope the port by function (content, enforcement, configuration, supervision), not by directory. Inventory the enforcement layer explicitly and verify each item is either carried over or has an equivalent on the target. Grep the migration diff for the enforcement paths; an empty result is a finding, not a pass.

3. Treat human-in-the-loop supervision as a control with no file representation. If the target surface removes the human, something executable has to replace that function or the gap must be recorded as accepted risk.

4. After the port, prove enforcement on the target surface with a negative test: trigger an action the control is supposed to block and confirm it blocks there, not just on the source surface.
