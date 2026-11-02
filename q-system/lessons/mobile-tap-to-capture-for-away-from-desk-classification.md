---
id: mobile-tap-to-capture-for-away-from-desk-classification
kind: pattern
title: Mobile Tap-to-Capture for Away-From-Desk Classification
date: 2026-11-02
---

When a repetitive judgment task has to happen away from a workstation (walking a site, standing at a shelf, watching playback on a handheld, interviewing in the field), stop handing reviewers a spreadsheet to fill in afterward. Build a single-purpose mobile page whose only job is to record one decision per item, instantly.

How to build it:

1. Reduce the decision to a closed set. List every outcome a reviewer can choose and confirm the set is small enough to fit on one thumb-reachable screen (roughly three to seven options). If the set does not close, this pattern does not apply yet — go finish defining the taxonomy first.

2. Render one item at a time. Show the item under review plus a row of large tap targets, one per outcome. No dropdowns, no free-text box, no multi-field form, no save button. Size targets for a thumb in motion, not a mouse.

3. Make the tap the commit. On tap, write the record to durable storage immediately — reviewer identity, item identifier, chosen outcome, timestamp. Do not batch in client memory, do not wait for a session to end, do not rely on the page staying open. Assume the device locks, the browser is killed, or the signal drops at any moment.

4. Advance automatically. After a successful write, move to the next item without further input, so the reviewer's rhythm is tap — tap — tap. Show a lightweight confirmation (a flash, a count) so the reviewer trusts the write happened.

5. Make the queue resumable and idempotent. Derive the next item from what has not yet been recorded, keyed by item identifier, so reopening the page on any device picks up exactly where work stopped and a repeated tap overwrites rather than duplicates.

6. Handle intermittent connectivity explicitly. Either require connectivity and fail loudly on a failed write (never silently swallow it), or queue locally with a visible unsynced counter and flush on reconnect. Silent loss is the one failure mode this pattern exists to prevent.

7. Add an escape hatch, not a second form. Provide one 'flag for later' tap for items that do not fit the closed set. Those items get routed to the full-featured desktop workflow instead of forcing a text field onto the mobile page.

8. Instrument throughput. Track items per session and elapsed time per tap. If time per item climbs, the outcome set is probably too large or ambiguous — that is a signal to split the taxonomy, not to add fields.

Where this pattern stops: it is for short, categorical, low-context judgments. As soon as a reviewer needs to write prose, cross-reference other records, compare several items side by side, or justify a decision, the mobile tap page is the wrong tool — route that work to a full interface on a real screen. Attempting to grow the tap page into a general-purpose form is how it loses its speed advantage and its reliability.

Why it beats a spreadsheet filled in later: deferred entry means every observation lives in short-term memory or on paper until transcription, so interruptions cost whole batches, transcription introduces errors, and nobody can see progress mid-pass. Committing at the moment of judgment removes the memory window entirely and makes partial work permanently valuable.
