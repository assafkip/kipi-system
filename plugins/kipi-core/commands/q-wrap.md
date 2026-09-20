---
description: Evening wrap: end-of-day health check. Closes open loops, catches missed debriefs, previews tomorrow.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

Run the end-of-day wrap.

```bash
QROOT="q-system"; [ -d "$QROOT" ] || QROOT="."; echo "QROOT: $QROOT"
```

Work the `Evening wrap (/q-wrap)` section as the 5-step checklist it is, not as
prose.

`/q-handoff` is chained automatically at the end. The founder never runs it
separately after a wrap.

```bash
python3 "$QROOT/.q-system/loop-tracker.py" list
```

A loop that is genuinely dead gets closed with its reason, never left to rot.
Report effort, not outcomes: "you sent 4 outreach messages" is the shape, not
"nobody replied" (`.claude/rules/audhd-interaction.md`).

The canonical spec is the `Evening wrap (/q-wrap)` section of `q-system/.q-system/commands.md`.
Read it there and follow it; this file does not restate it, so it cannot drift
from it. That spec already reaches every instance -- `kipi-update.sh` copies
`git archive HEAD -- q-system/` with `rsync -a --delete` and `.q-system` is not
in `INSTANCE_OWNED_SUBTREES`. What was missing was never the spec, it was a file
at a path the slash menu loads from (ASK-1927).
