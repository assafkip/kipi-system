---
id: keep-a-single-ledger-of-record-for-re-measured-claims
kind: methodology
title: Keep a Single Ledger of Record for Re-Measured Claims
date: 2026-10-12
---

Problem: A finished analysis document that passed its review gates was later found, by a cold second-opinion reviewer, to contain several factual errors. The numbers had been re-measured or corrected during the work, but the deliverable still carried stale or inconsistent values. Two process gaps allowed this.

Gap 1: No single source of truth for derived claims. The team had a tool that could record each verified fact (claim, source, command, result, timestamp) in an append-only ledger and then check that every number and quoted span in a document traces to a ledger row. It was never adopted for this workstream, and the tool treated a missing ledger as 'not opted in' and silently stood down rather than failing. So nothing checked the deliverable's numbers against a record. A separate chain-of-custody system for raw external evidence existed and was followed well, but it answers a different question (is our copy of the source authentic) from the one that failed (does this derived claim match the current, corrected state of the analysis). Nothing filled that second role.

Gap 2: Gates ran once, against the original scope, and were not re-run after the content changed.

How to apply:
1. Separate two kinds of evidence and give each an owner: (a) raw-source preservation, which proves a captured artifact is authentic, and (b) derived-claim verification, which proves a figure in the deliverable equals the current computed result. Having (a) does not cover (b).
2. Keep an append-only ledger for (b). Each row holds the claim, its source, the exact command or method that produced it, the result, and when it was verified. When a metric is re-measured, append a new row instead of editing prose in place.
3. Make the deliverable's numbers and quotes mechanically resolvable to ledger rows, and run that check as a gate before delivery.
4. Make opt-in tooling fail loudly for work that should be covered. A check that silently skips when its data file is missing gives false assurance; require explicit initialization at project start, or flag 'ledger absent' as a warning or failure on deliverables.
5. Treat any scope change, correction, or re-measurement as invalidating earlier gate results. Re-run all gates against the final content, not the original scope.
6. Before declaring done, get a cold review from someone or something without the working context, and compare its findings to the ledger. Errors it finds that the ledger would have caught indicate a process gap rather than a one-off slip.
