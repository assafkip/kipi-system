---
id: two-dead-components-one-symptom-two-unrelated-causes
kind: methodology
title: Two dead components, one symptom, two unrelated causes
date: 2026-09-07
---

When several components fail at the same moment with the same user-visible symptom, the shared timing is a hypothesis, not a finding. Diagnose each failure to its own root cause before fixing either one. A single fix applied to a cluster usually repairs one member and leaves the other broken in a way that now looks fixed, because the shared symptom went quiet.

## The procedure

1. **Split the cluster first.** Write down each failing component and its exact error text separately. Different error classes under one symptom (a missing-file error next to a connection-closed error) are strong evidence of independent causes.
2. **Classify each cause before fixing.** Two classes behave differently. An environment-trigger cause means a setup step was never performed here; nothing in the code is wrong. A latent-defect cause means the configuration or invocation was always wrong and only now met the conditions to fail. Retrying or reinstalling cannot fix the second class, and rewriting code cannot fix the first.
3. **Use the healthy peer as the control.** If one deployment or environment works and another does not, the difference between them is the evidence. Compare what exists on disk and what the invocation actually resolves, not what the documentation says both should have.
4. **Verify with the real entry point.** Confirm the fix by exercising the thing that failed, for example importing the modules the process imports and parsing the file it loads, not by observing that a process starts or that a command exits zero.

## Two causes worth knowing by name

**Documented setup that was never run.** When first-run setup lives only in prose, some environments will simply not have it. The interpreter or runtime path in a config points at something a human was supposed to create. It works everywhere the step happened and fails silently everywhere it did not. The durable fix is a setup step that is executed and checked, not described, plus a startup check that reports the missing prerequisite by name instead of a generic connection failure.

**A runner invoked in the wrong mode, resolving dependencies outside the project lock.** Modern tool runners accept both a project and a bare entry file, and quietly choose a different dependency resolution strategy for each. Passed a bare file, a runner can treat it as a standalone script, resolve dependencies into its own cache, and ignore the pinned lock sitting right next to it. Everything appears pinned; nothing is. The failure surfaces later as an import error when an upstream release renames a symbol. The tell is that the resolved dependency versions do not match the lock. Check what the invocation actually resolved, and prefer the invocation form that names the project rather than the file.

## The transferable rules

- One symptom does not imply one cause. Count the causes, not the symptoms.
- A pinned lock only protects the invocation mode that reads it. Verify the resolved versions, not the presence of the lock.
- Config that points at an artifact a human must create by hand is a latent outage in every environment where that hand never moved.
- A component that is absent and a component that is broken look identical to a caller that only sees connection failed. Make the startup error name the missing prerequisite.
- Fix verification names what was run and what it returned. A quiet symptom is not evidence.
