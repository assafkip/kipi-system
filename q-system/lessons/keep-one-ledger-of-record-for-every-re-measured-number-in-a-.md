---
id: keep-one-ledger-of-record-for-every-re-measured-number-in-a-
kind: pattern
title: Keep one ledger of record for every re-measured number in a deliverable
date: 2026-10-04
---

Situation: a finished analysis passed all its review gates, then a cold second reviewer found several factual errors. The numbers had been re-measured during the work, but earlier figures survived in the final document.

Cause: the project had a tool for exactly this, an append-only ledger with one row per verified fact (claim, source, command, result, timestamp) and a checker that confirms every number in a document traces to a row. It was never adopted for this workstream. The checker treated a missing ledger as 'not opted in' and stood down, so nothing failed. A separate evidence system existed, but it answered a different question: 'do we hold a tamper-evident copy of the external source?' It did not answer 'does this derived, computed claim match the current corrected state of the analysis?' No mechanism held that second role.

Pattern:
- Separate raw-source evidence (provenance of what you collected) from derived-claim evidence (what you computed from it). They need different stores; one does not substitute for the other.
- Start the derived-claim ledger on day one of the work, not at the end. Record each computed figure with its command and result at the time you measure it.
- When a figure is re-measured, append the new row and mark the old one superseded. Never edit in place and never keep two live values.
- Run the traceability check against the final document as a blocking step: every number and quoted span must resolve to a current ledger row.
- Make 'no ledger exists' a failure for work that claims to be verified. A check that silently stands down when its input is absent gives green results on unchecked work.
- Re-run all gates after any scope or content change, not only on the original draft.
- Add a cold reviewer who has not seen the working notes; they catch what the author's context hides.
