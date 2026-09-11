---
id: assert-what-went-into-a-composed-artifact-not-just-that-it-c
kind: pattern
title: Assert what went into a composed artifact, not just that it came out valid
date: 2026-08-10
---

## The failure shape

A component assembles one artifact out of several source files: a prompt, a config bundle, a merged ruleset, a generated document. The assembly step silently drops or stales part of its input. Nothing raises, because every failure mode still produces a well-formed result:

- A truncated string is still a valid string.
- A stale file is still a readable file.
- A missing optional source is indistinguishable from an empty one.

The only observable is downstream quality, which is a judgement call, and judgement gets applied months later by a human noticing one wrong detail. Everything in between reports success.

## How to build so this cannot hide

**1. Declare the input set, then check the output against it.**
Write the required sources as data (a manifest, a list, a schema) rather than as a sequence of read calls scattered through the assembler. After assembly, assert that every declared source contributed: a marker per source, a per-source byte or token count, a coverage record. "Did it produce something" is not the check. "Does what it produced contain what I declared" is.

**2. Make partial input fail closed.**
If a declared source is absent, unreadable, or older than a freshness bound, raise instead of continuing with the remainder. Optional sources get an explicit `optional: true` in the manifest so absence is a decision recorded once, not an accident repeated on every run.

**3. Log the composition, not the outcome.**
Emit which sources were read, their sizes, and their modification times on every run. This turns a silent 30%-of-intended assembly into a line someone can grep, and turns a stale source into a visible timestamp instead of an invisible one.

**4. Delete the truncation knob instead of documenting it.**
Any size limit, sample cap, or budget cutoff in an assembler is a silent-truncation mechanism. A comment explaining it does not stop it from firing. If the limit exists for a real constraint, make exceeding it an error the caller must handle; if it exists because someone once guessed a number, remove the parameter entirely. A magic constant with no recorded budget calculation, no date, and no alternatives-considered note is one nobody will ever question and everybody will inherit.

**5. Give the union of fragmented guidance one owner.**
When the same category of input lives in more than one place (two config directories, two plugin scopes, two layered rulesets), no single reader is responsible for the whole set, so the assembler quietly reads one and ignores the rest. Fix it by naming one resolver that enumerates all locations and returns the merged set. Every consumer goes through that resolver. A file sitting unread in the same directory as one that is read is the signature of this defect.

**6. Watch for the correction loop that is open at both ends.**
High-precedence override files (the ones whose own headers say "loaded last, highest weight") are the most likely to be silently unread, because their content is small and their absence changes nothing structurally. If a system records corrections into a file, add a check that the file is actually being consumed by whatever is supposed to obey it. Written-down feedback that never reaches the consumer is worse than no feedback: it creates the belief that the loop is closed.

## The check that would have caught it

One assertion, run on every assembly: `assembled_artifact` contains a distinguishing marker from each declared source, and each source's timestamp is within the freshness bound. It fails red on both the truncation case and the staleness case. Before shipping it, force it red by removing one source, so you know it can fail for the reason you care about.

## Generalizes to

Prompt construction, config merging, template rendering with partials, bundler entry-point resolution, document generation from multiple fragments, any migration that merges records from several tables. Anywhere the output is structurally valid regardless of how much of the input arrived.
