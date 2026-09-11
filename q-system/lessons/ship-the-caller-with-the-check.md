---
id: ship-the-caller-with-the-check
kind: methodology
title: Ship the caller with the check
date: 2026-08-10
---

A validator, guard, or test that no runner invokes changes nothing. Treat the invocation path as part of the deliverable, not as follow-up bookkeeping.

HOW:

1. Before writing the control, name its caller. Pick the exact invocation surface it will live on: pre-commit runner, CI job, build target, test manifest, startup check. Write that surface's entry in the same commit as the control itself.

2. Prove the wiring by making it fail. Run the pipeline (not the control directly) against an input the control rejects, and confirm the pipeline goes red. Running the script by hand and seeing a non-zero exit proves the logic, not the wiring.

3. Grep for the control's own name across every invocation surface and require at least one hit outside its own test file. Zero external references means it is unreachable. Do this as a closing step on any commit that adds a checker.

4. Add a meta-check that fails when a control has no caller, or when a test file exists that no manifest declares. Otherwise the class recurs: each new unwired control is invisible until someone happens to look.

5. When existing tooling already prints the miss, act on that line in the same session. A red status emitted by a routine job is a finding, not log noise. If a printed red is routinely scrolled past, that is a signal-routing defect worth its own fix: make it block, or route it somewhere that requires a disposition.

Done means: the control exists, a named runner invokes it, and the runner has been observed failing because of it.
