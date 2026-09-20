---
description: Write the session handoff note so the next session resumes with context instead of from zero.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

Write the handoff note for the next session.

```bash
QROOT="q-system"; [ -d "$QROOT" ] || QROOT="."; echo "QROOT: $QROOT"
```

Output is `$QROOT/memory/last-handoff.md`, which `q-system/CLAUDE.md` names as
the file a new session reads first.

Provenance is enforced on that file, not merely encouraged:
`handoff-provenance-lint.py` runs PostToolUse on it and exits 2 on a
measurement-shaped line carrying no `[verified: ...]`, no `ev-` claim id and no
`{{UNVERIFIED}}` marker (`.claude/rules/evidence-ledger.md`). Write the number
with where it came from, or label it.

Every open item carries its literal next command. A summary nobody can act on is
the thing this note exists to replace.

The canonical spec is the `Session handoff (/q-handoff)` section of `q-system/.q-system/commands.md`.
Read it there and follow it; this file does not restate it, so it cannot drift
from it. That spec already reaches every instance -- `kipi-update.sh` copies
`git archive HEAD -- q-system/` with `rsync -a --delete` and `.q-system` is not
in `INSTANCE_OWNED_SUBTREES`. What was missing was never the spec, it was a file
at a path the slash menu loads from (ASK-1927).
