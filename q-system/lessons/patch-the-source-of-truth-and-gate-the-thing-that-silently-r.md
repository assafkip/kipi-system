---
id: patch-the-source-of-truth-and-gate-the-thing-that-silently-r
kind: pattern
title: Patch the source of truth, and gate the thing that silently regresses
date: 2026-07-20
---

When a change must survive rebuilds and deploys, apply it to the input the build reads, not to a generated or deployed artifact downstream. A generator that consumes a source verbatim will overwrite anything added only to its output, and the patched artifact creates a false signal that the change is wired when the next build erases it.

HOW:

1. Trace the build backward before editing. Find the artifact the generator reads verbatim and edit that. If you edited a downstream copy, confirm the generator regenerates it, then move the change upstream.

2. Add a failable check for the exact property that can silently disappear. Existing selftests that assert brand copy, content types, and endpoints will still pass while a required-but-invisible element (a tracker, a header, an integration hook) is stripped. A gate that never inspects the thing cannot catch its removal. Assert presence of the specific element, and prove the check fails when the element is absent.

3. When more than one path can serve the same output, write down which one is authoritative and when each is rebuilt and deployed. Undocumented parallel serving paths let a committed artifact drift from both its source and production, and that drift is what hides the regression. Either collapse to one path or make the contract explicit and enforced.
