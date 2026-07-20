---
id: enforcement-lives-in-the-runtime-not-in-the-files-you-copy
kind: pattern
title: Enforcement lives in the runtime, not in the files you copy
date: 2026-07-20
---

When a system feels "controlled," locate where the control actually executes before you assume it travels. Two very different things can produce the same visible behavior: content (commands, templates, prompts, skill definitions, rule docs) and enforcement (the mechanisms that fire on every action). Enforcement usually lives in the runtime, not the content: a human watching the loop synchronously, hooks/validators that run on every tool call, and the settings the process actually loads at startup. None of those are inside the content files.

So a copy that moves content by directory ports zero enforcement. You get the same commands and templates and feel done, while the thing that paced and gated the original stays behind. Grep the copy payload for the enforcement surfaces (settings, hook registrations, per-call guards); if they return nothing, you copied the appearance of control, not control.

Watch for a second inversion: an automated or headless agent often runs with settings-loading disabled by construction. If it starts with an empty settings source and permissions bypassed, it loads no rules, no hooks, no config, no supervisory human. Backfilling the rule/content layer then leashes only the rarely-used interactive path a human still drives, and leaves the automated agent, your primary surface, completely unleashed.

HOW to apply:
1. For any behavior you rely on, name the enforcing mechanism and where it runs. If the answer is "it's written in a file," that is content, not enforcement.
2. Before trusting a port or clone, confirm the enforcement surfaces are present and active in the new home, not just the content directories.
3. Check what settings the running agent actually loads. An agent that loads none inherits none, regardless of what sits in the repo.
4. When two surfaces exist (interactive, human-watched vs. automated, headless), verify the control on the surface that carries the real traffic, not the convenient one.
5. Resist the single tidy cause. Missing enforcement is often several structural gaps at once (scope of the copy, plus the runtime's load semantics), and the most important one may invert your first hypothesis.
