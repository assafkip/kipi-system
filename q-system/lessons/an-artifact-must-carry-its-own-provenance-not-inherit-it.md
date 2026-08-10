---
id: an-artifact-must-carry-its-own-provenance-not-inherit-it
kind: pattern
title: An artifact must carry its own provenance, never inherit it from where it was filed
date: 2026-08-05
---

An output file whose identity comes from its location, its filename, or the intent of the script that produced it will eventually describe something it did not do. Nothing in the artifact itself contradicts the label, so the mismatch is invisible to every later reader.

Observed when an automated review was run from a stale copy of a runner left behind in a scratch directory. The stale copy hardcoded three things: an output directory named after one engine while invoking a different one, a review root pointing at a parent directory that was not a repository at all, and a process name identical to the canonical runner's. The result was a file that looked like a review by one tool, was produced by another, contained a verdict formed with no diff available, and could not be distinguished from a real review by reading it. A process-level attempt to stop it would have matched the legitimate run instead.

The same class explains a family of quieter failures: a prompt asserting that references are resolved when they are only pattern-matched, a note instructing a reader not to be shown a value printed directly beside it, and a validator whose documentation names a helper that has since been deleted. In each, an artifact asserted something about the system that the system did not do, and each satisfied whatever checker was watching.

How to apply:

1. Every generated artifact records, inside itself, what produced it: the tool actually invoked, the root it actually read, and the resolved identifier of the input it examined. A reader must never have to inspect an exited process to learn what a file means.
2. Treat a directory name, a filename convention, or a script's stated intent as a hint, never as provenance. Where a label and the content disagree, the content is the truth and the label is a finding.
3. Neutralise stale copies of executable tooling, and make surviving copies distinguishable at the process level, not merely absent from filesystem searches. Sharing a process name with the canonical runner makes targeted operations unsafe.
4. Prose adjacent to a value does not constrain the value. A warning not to display something, printed next to the thing itself, has already failed. Move the enforcement into the code path that emits.
5. When a comment names a helper, a flag, or a guarantee, it is a claim about the code and it decays. Prefer deriving documentation from the structures themselves, and treat a comment contradicted by the code as a defect rather than as stale text.

The general contract: an artifact that inherits its identity from its context is a claim nobody verified. Make it self-describing, and a wrong run becomes self-evident instead of requiring forensics.
