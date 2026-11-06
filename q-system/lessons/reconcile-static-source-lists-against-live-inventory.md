---
id: reconcile-static-source-lists-against-live-inventory
kind: pattern
title: Reconcile Static Source Lists Against Live Inventory
date: 2026-10-31
---

When a process draws its inputs from a hand-maintained list of sources (directories, feeds, tables, modules, config entries), treat that list as a claim to be verified rather than a fact. Validate it against an independent enumeration of what actually exists, not just against the items it already names — a list can only ever be self-consistent, never self-correcting.

How to apply it:

1. Find the authoritative enumeration. Identify a way to list the full universe of candidate inputs from the substrate itself (scan the container, query the catalog, walk the namespace) rather than from the curated list.
2. Diff both directions. Compute (a) items present in reality but absent from the list — silent omissions, the dangerous class; and (b) items in the list but no longer present — stale entries that mask failures or throw noise. Report both.
3. Automate the diff as a check. Put it in a test, a startup assertion, or a scheduled job so the comparison runs on every change instead of only when someone suspects a gap. Fail loudly or emit a warning with the unmatched names.
4. Decide the default for new items. Either make discovery dynamic (enumerate first, then filter with an explicit exclusion list) or keep the include list but require the diff check to pass. Exclusion-by-default silently drops growth; inclusion-by-default surfaces it.
5. Verify coverage at the output, too. Confirm each expected input category actually contributes to the result. An input can be listed, read, and still be dropped downstream by filtering, deduplication, or ranking — presence in the list is not proof of representation in the output.
6. Record the rationale for exclusions. When something is deliberately left out, note why next to the exclusion so a later reader can tell intent from oversight.

When it is worth the effort: whenever the underlying material grows, is added to by multiple people, or is maintained on a different cadence than the list. The gap between list and reality widens with time, and the failure mode is silent — output looks complete because nothing errors.

When to skip it: a genuinely small, closed set that is not expected to change, where the list and the reality are maintained in the same commit by the same person. There, the check costs more than the drift it would catch.
