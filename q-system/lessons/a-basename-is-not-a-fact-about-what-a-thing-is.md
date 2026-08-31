---
id: a-basename-is-not-a-fact-about-what-a-thing-is
kind: pattern
title: A name is not a fact about what a thing is
date: 2026-08-06
---

Matching on a name — a basename, a directory name, a path segment, a flag string — is cheap, readable, and usually right, which is why it keeps getting reached for to make semantic decisions. But a name is a label someone chose, not a property the code verified. The failure is silent in both directions: a thing with the expected name that is not the expected thing, and the expected thing under a name nobody enumerated. Neither shows up in a test written by the same person who chose the predicate, because they will name their fixture the expected way.

Three instances in `kipi-update.sh` and its guard, all found in one session on 2026-08-06:

**An allowlist of names deciding what is founder data.** `kipi-update-deletion-guard.py` protects seven instance-owned *directory names*. A tracked instance-only script is not one of them, so the guard passed it. The tempting fix — add `scripts` — is worse than the gap: `q-system/.q-system/scripts/` holds 141 skeleton-owned files and the skeleton has legitimately deleted 6 of them over its history, so the name-based entry would refuse those propagations on all 24 instances. Instance-only and skeleton-owned files are interleaved *in the same directory*. No name separates them; only provenance does.

**A flag compared against a value it can never hold.** The auto-commit was guarded on `[ "$DRY_RUN" != "1" ]` while `DRY_RUN` only ever holds `""` or `--dry-run`. The name of the variable made the intent obvious enough that nobody read the value, and the condition could never be false — a guard indistinguishable from its own absence.

**A directory named `build` assumed to be a build cache.** The dry-run model build strips any directory whose basename is `target node_modules .venv venv __pycache__ .next dist build .pytest_cache .mypy_cache .ruff_cache`, then copies `.git` verbatim. `design-room/build/gate-report.md` is authored gate output living under a directory that happens to be called `build`, so the model saw a tracked deletion, read the tree as dirty, and reported the instance FAILED. A real update was unaffected — the excludes apply only to the model copy — but a fleet health check driven off `--dry` would page on healthy instances.

What connects them is not carelessness. In each case the name was a genuinely good heuristic that was right nearly every time, and the exceptions were invisible precisely because they were rare.

How to apply:

- Ask what property you actually need, then ask whether the name *verifies* it or merely *suggests* it. "Is this a build cache" is answered by "does it contain tracked files", not by its basename. "Is this founder data" is answered by provenance — did the skeleton ever ship it — not by a directory name.
- When a name-based predicate is the pragmatic choice, write down what it does NOT cover, in the code, next to the predicate. An undocumented heuristic reads as a specification to the next person.
- Adding a name to an allowlist to close a reproducer usually leaves the class open and can open a worse one. Measure the population the new name would also match before adding it.
- Prefer a predicate that fails toward refusing a real operation over one that fails toward permitting it — but measure the false-positive rate first, because a guard that blocks healthy work gets switched off, and a gate that is off protects nothing.
- If the same shape appears a third time in one component, the fix is not a third patch. The component has a habit, and the habit is the defect.
