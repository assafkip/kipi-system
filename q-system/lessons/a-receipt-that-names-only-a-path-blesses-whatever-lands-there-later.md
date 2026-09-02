---
id: a-receipt-that-names-only-a-path-blesses-whatever-lands-there-later
kind: pattern
title: A receipt that names only a path blesses whatever lands there later
date: 2026-09-02
---

The first promotion receipt recorded the path of the file that moved. Anything written at that path afterwards would have inherited the blessing. The fix binds the receipt to the git blob hash of the content AND to the skeleton's blob at promotion time (the base), so the receipt is spent the moment the skeleton moves past it. Codex finding-1 on the PRD and the Claude adversarial pass on issue 9 (prd-lessons-rail-and-up-rail).

How to apply:

1. A receipt authorises content, never a location: record the content hash and the state it was measured against.
2. Make the receipt expire by construction. Ask "what changes after this that should invalidate it?" and record that value too.
3. Test the stale case explicitly: the same receipt, the file edited afterwards, must refuse.
