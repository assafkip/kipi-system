---
description: Ad-hoc one-off output (a specific email, DM, or talking points) written to output/drafts/.
argument-hint: [type] [audience]
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

Generate one ad-hoc output. Ephemeral by design: it lands in `output/drafts/`
and is not canonical.

`$ARGUMENTS` is `[type] [audience]`. Structured deliverables (talk tracks,
workflow packs) are `/q-create` instead.

```bash
QROOT="q-system"; [ -d "$QROOT" ] || QROOT="."; echo "QROOT: $QROOT"
```

Voice is not optional on anything another person reads
(`.claude/rules/voice-enforcement.md`). Two rules the lints cannot infer for you:
a cold DM never opens with a greeting and leads with THEIR pain; an email to
someone the founder already knows opens the way he actually opens one.

The inverse of this mode is the kipi-core `improve` SKILL, which critiques an
outside idea against what this system already has. It is a skill, not a command.

The canonical spec is the `/q-draft [type] [audience]` entry in `q-system/.q-system/commands.md`.
Read it there and follow it; this file does not restate it, so it cannot drift
from it. That spec already reaches every instance -- `kipi-update.sh` copies
`git archive HEAD -- q-system/` with `rsync -a --delete` and `.q-system` is not
in `INSTANCE_OWNED_SUBTREES`. What was missing was never the spec, it was a file
at a path the slash menu loads from (ASK-1927).
