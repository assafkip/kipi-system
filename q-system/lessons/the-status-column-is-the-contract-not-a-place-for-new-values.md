---
id: the-status-column-is-the-contract-not-a-place-for-new-values
kind: pattern
title: The status column is the contract, not a place for new values
date: 2026-09-02
---

The candidates listing invented `stale(done)` when a receipt existed for an earlier version, and counted receipts from other instances as this instance's. The contract said exactly four statuses; the extra value would have leaked into every consumer. Codex, both passes, issue 12 of prd-lessons-rail-and-up-rail.

How to apply:

1. When a field's values are enumerated in the contract, normalise to that set at the boundary and put extra information in a note, never in the enum.
2. Filter records by their owner before reporting them as someone's status.
