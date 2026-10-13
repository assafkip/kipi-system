---
id: reconcile-summary-counts-against-data-already-retrieved
kind: methodology
title: Reconcile Summary Counts Against Data Already Retrieved
date: 2026-10-12
---

When a report shows a mismatch between an aggregate figure and the itemized rows you parsed (for example, a counter says 7 but you listed 3), treat the gap as a defect in your own parsing and resolve it before reporting. Do not explain it away with a plausible guess such as 'probably nested items'.

Practice:
1. Before parsing a payload, inspect its full shape. List every field on a record, including nested arrays and child collections, and note which ones are populated.
2. Flatten or recurse through nested structures so the parsed set represents the whole dataset, not only the top level.
3. Reconcile totals. Compute the itemized count from the data you hold and compare it to the aggregate counter. If they match, state the verified number. If they still differ, say exactly what is unexplained instead of asserting a cause.
4. Ban unverified hedges in findings. Phrases like 'almost certainly' or 'likely' that fill a gap the retrieved data could settle are a signal to go check the data first.
5. Verify state claims against the evidence. Statements such as 'still open', 'unanswered', or 'missing' need confirmation from all related records (including replies, follow-ups, and timestamps) before they are reported, because a wrong negative can send someone to redo finished work.
6. Scope the claim. If you only examined part of a dataset, label the result as partial rather than presenting it as complete.

A useful check: before sending, ask whether every number and every 'nothing happened' statement is backed by data you actually opened, not data you assumed existed elsewhere.
