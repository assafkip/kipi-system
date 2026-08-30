---
id: give-a-guard-an-explicit-allowlist-never-a-catch-all-default
kind: pattern
title: Give a guard an explicit allowlist, never a catch-all default
date: 2026-08-10
---

When a mechanism acts on inputs it classifies (paths, event types, record kinds, routes), the default branch decides everything nobody thought about. If that default is "act", the mechanism's real scope is not what the classification table says — it is the whole input space, and every category added later joins silently, with no decision and no review.

How to apply:

1. Split the classifier's output into three explicit outcomes: act, skip, and unknown. An input matching no entry is unknown, not act.
2. Make unknown loud and inert. Refuse, log, or surface it. A mechanism that acts on an unclassified input has taken authority nobody granted it.
3. Write the check that pins this: feed the mechanism an input deliberately absent from every table entry and assert it does not act. If that test cannot go red, the default is still open.
4. Reconstruct the scope from behaviour, not from the table. Enumerate what the mechanism actually touches over a real workload and compare against the intended list; the gap is the inherited default.

Why this class of defect stays hidden: it fires only on inputs nobody modelled, so every classified case keeps behaving correctly forever and the defect lives entirely in the blind spot. Symptoms then surface far apart and each looks local and unrelated, so no single vantage point connects them. Two consequences follow. When you find one such symptom, do not fix it in place — ask what shared default produced it and look for siblings. And when several odd, unconnected behaviours accumulate around one mechanism, treat "these are unrelated" as the hypothesis to disprove rather than the conclusion; a second reader working from a different angle often finds the symptom you structurally cannot see.
