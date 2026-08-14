---
id: a-citation-is-re-read-at-write-time-never-recalled
kind: pattern
title: A citation is re-read at write time, never recalled
date: 2026-08-05
---

An evidence ledger makes claims traceable, but traceability is not accuracy: a citation points at a row, and nothing checks that the row says what the sentence claims. The failure is quiet and it compounds, because a cited number reads as verified. It is worst in a system that stores an id next to a short summary, since the summary is what gets remembered and the summary is lossy. Three miscitations in one session, all from recalling an id instead of opening it: a shape-profile count ("271 found") rewritten as an accuracy rate ("271 of 271"), a row concluding a component was NOT broken quoted for the one bad stratum out of five to prove it was, and a row recording that a transfer had NOT landed cited as proof it had. The first had been propagating through a decision log for three days, motivating a decision.

HOW:
1. Re-read the row at the moment you write the sentence, not from the summary you are carrying. Make that mechanical: a `--show <id>` mode on the linter that prints claim, result, source and date, so opening the record costs one command and skipping it is a choice rather than an oversight.
2. Gate the two failure shapes a machine can actually decide. ORPHAN NUMBER: every number in the citing sentence must appear in the row's claim or result, after normalizing the formats that make a real quote look absent ("88 of 88" against "88/88", "2,831" against "2831"). POLARITY FLIP: if the row's claim carries a negation and the citing sentence does not, or the reverse, block. Measure the gate against your actual scars and publish the score; two of three is a useful gate, and claiming three of three without running it is the same defect the gate exists to catch.
3. State the boundary in the gate's own docstring, naming the scar it does NOT catch. A negation elsewhere in the sentence masks a polarity flip, and regex cannot decide which clause a citation binds to. A gate whose silence is trusted must say what its silence does not mean.
4. Scope the gate to where claims are written (canonical docs, specs, client output), never to code. A test fixture legitimately holds a fake id, and a lint that fires on every edit gets switched off.
5. Correct a bad claim in place with a CORRECTED note naming the false statement. Deleting it silently leaves the next reader unable to tell an audited line from an unexamined one, and the wrong number usually has copies elsewhere that the note is what makes findable.
6. Treat a stored state file the same way. Notes about a fast-moving external system are only as fresh as the session that wrote them; re-verify against the live system before building on them, and record which claims are observation and which are someone's report.
