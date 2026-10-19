---
id: keep-a-single-ledger-of-record-for-derived-claims-and-re-ver
kind: methodology
title: Keep a single ledger of record for derived claims, and re-verify after every scope change
date: 2026-10-19
---

Problem: a finished analysis that had passed its review gates still contained several factual errors, which an independent cold reviewer caught. Two systemic causes recur in many projects.

1. No single source of truth for re-measured numbers. When a metric is recomputed or corrected mid-analysis, older copies of it linger in summaries, tables, and prose. A tamper-evident archive of raw external evidence does not solve this, because it answers 'do we hold an untouched copy of the source?' and not 'does this derived claim match the current state of the analysis?'. A verification mechanism may also exist but silently stand down when nobody has opted in, so its absence of complaints looks like a pass.

Practice:
- Keep an append-only ledger of verified facts. Each row records the claim, its source, the exact command or method used, the result, and a timestamp. Corrections are new rows, never edits.
- Make every number and quoted span in a deliverable traceable to a ledger row, and have a check that fails the document when it cannot resolve one.
- Treat a missing ledger as a failure for any project that produces deliverables, not as 'not yet opted in'. Initialise it at project start. Audit for tools that default to inactive and report that state loudly.
- Keep the two evidence roles distinct: source preservation (is the raw input intact?) and claim verification (does the derived statement match current computed reality?). Make sure something owns each role.

2. Gates that run once, against the original scope. Review gates that pass at an early point do not cover later changes to scope, data, or conclusions. Once the work moves, a pass no longer describes the artifact.

Practice:
- Re-run all gates after any material change to scope, inputs, or a headline figure, and record which version each gate evaluated.
- Invalidate prior gate passes automatically when the content they covered changes.
- Before finalising, get a cold second-opinion review from someone or something with no exposure to the working context. Give it the final document and the evidence base, and ask it to recompute the key claims independently.

Outcome: derived claims stay tied to a current, verified record, and a gate pass reliably means the delivered artifact was checked, not an earlier draft of it.
