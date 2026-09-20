---
description: LinkedIn engagement. Proactive hitlist from tracked targets, or a reactive comment on a post the founder shares.
argument-hint: [dp-outreach]
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, WebFetch
---

Enter ENGAGE mode. Three directions, all spec'd in the same file:

- **Proactive** (no arguments): build the daily hitlist from the tracked targets.
- **Reactive**: the founder shares a post or a screenshot. Evaluate it for market
  intelligence through the 6 lenses FIRST, then generate one best comment. The
  system picks the style (`.claude/rules/auto-detection.md`).
- **`dp-outreach`**: the design-partner variant.

```bash
QROOT="q-system"; [ -d "$QROOT" ] || QROOT="."; echo "QROOT: $QROOT"
```

Reacting to someone else's content fires the social reaction gate
(`.claude/rules/social-reaction-gate.md`): extract the poster's claims and print
them ABOVE the draft, in the same turn. A "here are the claims, say go" turn is
refused by `voice-stop-gate.py`, and the follow-up turn classifies as not-routed,
so the draft would land ungated.

A reaction is about the poster's ideas. It does not pitch or name-drop the
founder's product unless he asked for that.

The canonical spec is the `/q-engage` entry in `q-system/.q-system/commands.md`.
Read it there and follow it; this file does not restate it, so it cannot drift
from it. That spec already reaches every instance -- `kipi-update.sh` copies
`git archive HEAD -- q-system/` with `rsync -a --delete` and `.q-system` is not
in `INSTANCE_OWNED_SUBTREES`. What was missing was never the spec, it was a file
at a path the slash menu loads from (ASK-1927).
