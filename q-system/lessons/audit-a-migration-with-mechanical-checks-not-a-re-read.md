---
id: audit-a-migration-with-mechanical-checks-not-a-re-read
kind: methodology
title: Audit a migration with mechanical checks, not a re-read
date: 2026-07-06
---

When you verify that a port, migration, or refactor preserved a set of required behaviors, do not ask a model (or yourself) to re-read the new code and judge whether each property survived. A read gives a soft yes/no that drifts run to run and quietly passes things it should catch. Instead, encode each required behavior as its own deterministic check that inspects the actual code or artifact: a grep, a string/AST match, a structural assertion, a count. Each check names the property, its severity, and a single verdict computed by the machine, not narrated by a reader.

How to build it:
1. Enumerate the invariants first. List every behavior the target must still exhibit after the change, one row each, before writing any check. The list is the contract; the checks are its enforcement.
2. Make each check look for the mechanism, not a synonym. Assert on what the behavior is implemented as (the call, the ordering constraint, the typed field, the edge or node it produces), so a check cannot pass on a lookalike. Prefer proving the producer exists over proving a keyword appears.
3. Give each check a severity and a binary verdict. High-severity gaps block; the output is a table of id, severity, verdict, finding, not prose. A machine-computed ok is trustworthy in a way a re-read ok is not.
4. Guard against the crude-match failure. A substring test flags lookalikes; a too-narrow test misses real regressions. When a check keys off identity (a name, a slug, a source), verify that identity is actually distinct, not collapsed.
5. Run it as a gate, not a report. The audit should exit non-zero on any high finding so it fails a pipeline, and rerun cheaply on every change. A judgment you cannot rerun deterministically is not an audit.

Use this whenever the question is whether the new thing kept doing all the things the old thing did. Reserve model judgment for properties that genuinely need it (tone, intent, completeness of reasoning); route every property that a grep, match, or count can decide into a check instead.
