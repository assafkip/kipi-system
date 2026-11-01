---
id: flag-diverged-targets-before-a-one-way-sync-writes
kind: pattern
title: Flag Diverged Targets Before a One-Way Sync Writes
date: 2026-10-31
---

## Problem shape

A one-way propagation step (template fan-out, shared-config push, scaffold refresh, monorepo vendoring) copies files from a source of truth into many targets. When a target has edited a file past what the source ever contained, a blind copy silently destroys that work, and the target's own checks only turn red *after* the write. The fix is not smarter merging; it is making the sync say out loud, before writing, which targets are ahead.

## HOW

1. **Record what the source has ever shipped per path.** Keep, or derive from history, the set of content hashes the source has published for each path. A target copy is "explainable" if its current tracked content hash is any one of those — current or older. Anything else means local divergence.
2. **Classify each existing file the sync would update** into: identical to current source (skip), equal to an older shipped hash (safe to fast-forward, stay quiet), or unexplainable (ahead/diverged — report it).
3. **Report by path, not by count.** Print every diverged path explicitly. Aggregate counts hide exactly the case that hurts.
4. **For code-like files, name the symbols at risk.** Parse both sides and list definitions (functions, classes, exported names, config keys, list entries) present in the target but absent from the incoming version. "This file diverged" gets skimmed; "this file defines three things your replacement does not" gets read.
5. **Emit the same report in both phases.** The dry run and the apply-time preflight must run the identical check and print the identical lines. A warning that exists only in dry run is a warning nobody sees in automation.
6. **Offer a refusal mode.** Provide a flag (and make it the default in CI) that aborts the sync for any target with unexplainable content, before the first write of that run — not mid-run, so no target is left half-updated.
7. **Handle the no-history case conservatively.** If you cannot establish what the source ever shipped for a path, treat the target copy as diverged rather than assuming it matches.

## Tests

- A target fixture whose copy contains one extra definition: the dry run must name that path *and* that definition.
- A target fixture whose copy equals an older shipped version: the report stays silent and the file fast-forwards.
- A target fixture identical to current source: no output, no write.
- Mutation test: force the "was this ever shipped?" lookup to always return true. The divergence report must go empty, and a test must fail. If everything still passes, the report is decorative.
- Refusal-flag test: with the flag set and one diverged target present, the run exits non-zero and no file on disk changed.

## Generalization

Any time you copy over content you did not author, the dangerous state is not "different" but "different in a way the source cannot explain." Build the ancestry check first, print paths and symbols, and gate on it before the write — not after the downstream checks fail.
