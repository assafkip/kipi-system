---
id: when-a-fix-recurs-audit-the-fixes-not-the-bug
kind: methodology
title: When a fix recurs, audit the fixes, not the bug
date: 2026-07-06
---

A defect that returns after several correct-looking patches is not a coding error you missed; it is a signal that every patch is aimed at the wrong altitude. Switch from bug-tracing (follow the symptom forward again) to fix-archaeology (look back at why the prior fixes recur).

How:
1. List every prior fix for this symptom and what each one targeted. If they all patched a surface the behavior renders through, but the behavior keeps regenerating, the surface is not the source.
2. Find the reference the behavior is actually cloned from — the single upstream definition, choke-point, or source of truth that reproduces the state. The recurring symptom is a faithful copy of that reference; patching downstream copies cannot hold.
3. Correct the reference, not the copy. A fix that changes what gets regenerated ends the recurrence; a fix that repairs one rendered instance is another patch that will recur.
4. Verify by re-deriving the behavior from the corrected reference, not by re-reading the patched surface.

When you are told to look at it from a different perspective and not repeat the prior approach, treat that as the tell: the altitude is wrong, not the diligence.

Method-honesty note: while doing fix-archaeology, confirm your own claims with the real check, not an inference. A tool that silently suppresses or truncates output (binary-mode search, paging, size limits) can make live code look dead; confirm a suspected dead choke-point is actually inert before declaring it so.
