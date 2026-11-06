---
id: make-sync-operations-idempotent-and-honest
kind: pattern
title: Make Sync Operations Idempotent and Honest
date: 2026-10-31
---

# Make Sync Operations Idempotent and Honest

When you propagate state from a source of truth to many targets, the same apply will eventually be run twice: a retry, a second operator, a scheduled job overlapping a manual run. If the operation re-writes the target regardless of whether anything changed, every duplicate run produces a spurious revision, a misleading audit trail, and noise that hides real drift. Three habits make these operations safe to repeat.

## 1. Record and read a provenance marker on the target

Each target should carry the identifier of the source version it was last synced from — a commit sha, a content hash, a monotonic version, whatever uniquely names the source state.

HOW:
- At the end of a successful apply, write the source identifier into the target (a metadata field, a marker file, a row in a sync table).
- At the *start* of every apply, read that marker first. If it already equals the incoming source identifier, skip the target and report `skipped (already at <id>)`.
- Treat the target's own record as authoritative. Do not infer prior state from orchestrator logs, chat history, ticket comments, or someone's recollection — those are the first things to go stale and the thing a second operator will never see.
- Make the skip path the default, with an explicit `--force` for the rare case where you must re-apply identical content.

## 2. Make dry-run report deltas, not activity

A preview that says `updated` for everything it touched is worse than no preview: it trains people to ignore it, and it cannot be used to decide whether to proceed.

HOW:
- Compute the intended end state, diff it against the current state, and emit one of `no change`, `would change: <fields/lines>`, or `would create`.
- Never let the dry-run vocabulary overlap with "was visited by the loop." If you need per-target progress, log it at a different verbosity.
- Summarize at the end: N unchanged, M changing. A preview whose summary is all-unchanged lets the operator stop with confidence.
- Have the dry run and the real run share the same diff function, so the preview cannot disagree with the apply.

## 3. Compare semantically before writing

Serializers reorder keys, change quoting, normalize whitespace, and stamp timestamps. A byte-level write-then-commit turns these into phantom changes, often with suspiciously symmetric insert/delete counts — equal lines added and removed is a strong smell that you rewrote a file into an equivalent form.

HOW:
- Render the new content, parse or normalize both old and new into a canonical form, and compare at that level. If equal, return without touching the target.
- Exclude generated-at timestamps and other volatile metadata from the comparison, or omit them from the artifact entirely.
- Keep the write and the commit behind the same guard, so "no semantic change" means no revision at all, not an empty or no-op revision.

## Test that locks it in

The regression test is small and catches all three failures: apply twice from the same source version, then assert the second run produced no new revision on the target, wrote no file, and reported `skipped`. Add a variant where the serializer's output is reordered but semantically identical and assert the same outcome. Without these assertions, idempotence silently rots the next time someone adds a field to the generated artifact.

## Why it matters

A no-op run that writes nothing is the signal that your sync is convergent: running it more often is free, concurrent operators cannot clobber each other, and any revision that *does* appear is real information. Once duplicate applies are free, you can run the sync aggressively instead of coordinating by hand around who ran it last.
