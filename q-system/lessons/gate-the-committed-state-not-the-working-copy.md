---
id: gate-the-committed-state-not-the-working-copy
kind: methodology
title: Gate the committed state, not the working copy
date: 2026-07-06
---

A green check on the working tree does not prove the change would exist on a fresh checkout. Two independent habits keep a passing artifact from shipping half-committed.

Staging: let the version-control system enumerate the working-tree delta rather than hand-naming files. An explicit allowlist is a manual transcription of a mental list with no feedback loop, so a dropped tail commits silently. Before every commit, read the staged-vs-working diff summary and reconcile it against what you actually touched. New files are the easiest to miss because they are untracked by default and absent from a plain diff.

Gating: a check that runs against the working directory is structurally blind to what is staged. It answers 'passes here, now' but never 'is committed and reproducible on a clean checkout.' For any gate whose subject is a file that must persist, add an explicit clause that the file is tracked and would survive a fresh clone. Verify PASS and verify TRACKED are two separate questions; proving one says nothing about the other.

The general invariant: whenever correctness depends on an artifact existing after the change lands, assert against a clean or committed state, not the live working copy. If the safety net only observes what is in front of you, an easy-to-make omission becomes an invisible one.
