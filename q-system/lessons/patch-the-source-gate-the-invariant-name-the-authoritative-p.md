---
id: patch-the-source-gate-the-invariant-name-the-authoritative-p
kind: pattern
title: Patch the source, gate the invariant, name the authoritative path
date: 2026-07-13
---

A feature that was 'added' can silently vanish if three conditions line up: the change was applied to a generated or deployed artifact instead of the source it is built from, no automated check asserts the feature's presence, and multiple serving paths exist with no declared owner.

The pattern to apply on any change to a built or deployed artifact:

1. Trace the artifact back to its build input before editing. If a build step reads a source file and emits the thing you are about to touch, your edit belongs in the source. An edit made downstream of the build is guaranteed to be erased on the next rebuild, while looking wired in the meantime. Ask: 'what process regenerates this file, and would my change survive it?'

2. When a property matters enough to add, it matters enough to assert. Extend the existing selftest or smoke check to fail if the property is absent from the built output. A gate that checks everything except the thing that regressed provides confidence without coverage; the check list should be updated in the same change that introduces the property.

3. If the same content can be served from more than one path (static hosting and a serverless function, a CDN copy and an origin, a committed artifact and a live build), write down which one is authoritative and when each is rebuilt or deployed. Undeclared parallel paths let a committed copy drift from both the source and production, which hides regressions because whichever copy you inspect may not be the one users receive.

The unifying test: for any change, be able to answer 'where does this live in the source of truth, what check fails if it disappears, and which serving path actually delivers it?' If any answer is unclear, the change is not done.
