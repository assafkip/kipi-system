---
id: a-pause-with-a-deadline-needs-a-mechanism-not-a-note
kind: pattern
title: A pause with a deadline needs a mechanism, not a note
date: 2026-08-17
---

When you switch an output path off "for now," the reason you wrote down is time-boxed but the switch is not. Unless something computes the end condition, the pause silently becomes permanent, and the guard that governs the switch will keep enforcing the pause forever with the original message attached.

## How to encode a bounded suppression

- Write the end condition as data the code reads, not as prose in a comment or manifest justification: an explicit expiry timestamp, a counter, or a named state the system can evaluate.
- Make expiry-without-review a failure, not a default. Past the date, the check that blocks re-enabling flips to demanding a decision: re-enable, or re-justify with a new bounded end.
- If you cannot express the end condition mechanically, do not phrase the reason as bounded. Call it indefinite and say who owns revisiting it, so nobody reads a deadline that no code enforces.

## How to make directional guards symmetric

Most guards on a delivery path answer one question: who is ALLOWED to write. That condition fires when something turns ON. Staying off can never violate it, so a disabled path is structurally invisible to the very gate that governs it.

- For each output path, write down both failure directions: an unexpected write, and an expected write that stopped. Confirm a check exists for each.
- The stop-side check is a liveness assertion keyed to the declaration, not the switch: a path declared as delivering, that has delivered nothing within its expected interval, is red.
- Weigh the two directions by who absorbs the damage. A wrong write usually lands on your artifacts. A missing write lands on a downstream consumer's belief that their data is current, and they have no way to notice.

## How to stop writing checks with no caller

A correctness check that is a manual one-shot is a check for the day someone remembers to run it. Its last recorded green run is also the last day it could have caught anything.

- Every check with a pass/fail verdict gets a caller: a scheduled run, a pipeline stage, or a gate. No caller means not wired.
- Record each run with its verdict and timestamp, and treat staleness as a signal: a check whose newest verdict predates the incident window was not protecting you during it.
- When a check exists but did not fire, the fix is the caller, not a rewrite of the check.

## The diagnostic

A downstream consumer reports that something stopped, and every check you own is green. That combination means your checks are all on one side of the asymmetry. Before hunting the specific break, list which of your green checks could ever have gone red for a stop, and which ones ran at all.
