---
description: Generate a structured deliverable (talk track, email, slide copy, diagram, memo) for a named audience.
argument-hint: [type] [audience]
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

Enter CREATE mode and generate one deliverable.

`$ARGUMENTS` is `[type] [audience]`. Both matter: a talk track for a CISO and a
talk track for a VC are different artifacts. If either is missing, ask once.

Structured deliverables live here. A one-off email, DM or set of talking points
is `/q-draft` instead.

```bash
QROOT="q-system"; [ -d "$QROOT" ] || QROOT="."; echo "QROOT: $QROOT"
```

Anything another person will read goes through the founder-voice skill before it
ships (`.claude/rules/voice-enforcement.md`). `voice-lint.py` and
`voice-substance-lint.py` run PostToolUse on the write and will say so.

The canonical spec is the `/q-create [type] [audience]` entry in `q-system/.q-system/commands.md`.
Read it there and follow it; this file does not restate it, so it cannot drift
from it. That spec already reaches every instance -- `kipi-update.sh` copies
`git archive HEAD -- q-system/` with `rsync -a --delete` and `.q-system` is not
in `INSTANCE_OWNED_SUBTREES`. What was missing was never the spec, it was a file
at a path the slash menu loads from (ASK-1927).
