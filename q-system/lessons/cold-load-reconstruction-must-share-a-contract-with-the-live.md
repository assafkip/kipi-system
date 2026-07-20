---
id: cold-load-reconstruction-must-share-a-contract-with-the-live
kind: pattern
title: Cold-load reconstruction must share a contract with the live view
date: 2026-07-20
---

When a view is built up incrementally by a live process (each event mutates in-memory state the user sees), and that same view must be rebuilt from durable storage on reload or navigation, the two are separate implementations of the same thing. When they drift, the live view looks correct while the reload path silently reconstructs something thinner or empty, even though the underlying records are all present.

HOW to handle it:

1. Define ONE reconstruction contract both paths obey. The live path and the cold-load path should produce the view by running the same projection over the same source records, not two hand-written builders. If you cannot merge them, at minimum assert that reload output equals the last live state for a known input.

2. Reproduce on the actual cold path. A refresh, a fresh session, or a nav-away-then-back is a different code path than in-session mutation. Test reconstruction from a cold start with only durable storage present, never from warm in-memory state.

3. Inspect record SHAPE, not just presence. Adjacent data restoring correctly (history, logs, trails) while the target view resets is the tell: the records exist, but the reconstruction step is not reading the fields it needs, or is keying off a status flag that filters them out. Confirm the durable records actually carry what the projection consumes.

4. Treat the Nth recurrence as a missing invariant, not another point fix. When a symptom class has been patched several times and returns, stop patching instances. The recurrence is the signal that no invariant guards the property. Write a check that fails whenever reload does not equal live, and wire it so a regression trips it automatically.

5. Name the authoritative source. Decide which store is the source of truth for the view and make reconstruction read only from it. Ambiguity about which record set is canonical is what lets one path populate while another stays empty.
