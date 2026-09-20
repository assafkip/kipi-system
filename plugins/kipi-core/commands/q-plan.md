---
description: Review relationships, objections and proof gaps, then propose prioritized next actions.
argument-hint: [focus]
allowed-tools: Bash, Read, Write, Glob, Grep
---

Enter PLAN mode.

`$ARGUMENTS` narrows the focus to a person, a vertical or a deal. Empty means the
whole board.

```bash
QROOT="q-system"; [ -d "$QROOT" ] || QROOT="."; echo "QROOT: $QROOT"
```

Read `$QROOT/my-project/relationships.md`, `$QROOT/canonical/objections.md` and
`$QROOT/my-project/current-state.md` before proposing anything. A plan built from
memory rather than from those files is the failure this mode exists to avoid.

Output is actions, not a dashboard. Every item carries an Energy mode (Quick Win
/ Deep Focus / People / Admin) and a Time Est, and batches with its own kind
(`.claude/rules/audhd-interaction.md`). If the founder cannot copy-paste it,
click it or check it off, it does not belong.

The canonical spec is the `/q-plan` entry in `q-system/.q-system/commands.md`.
Read it there and follow it; this file does not restate it, so it cannot drift
from it. That spec already reaches every instance -- `kipi-update.sh` copies
`git archive HEAD -- q-system/` with `rsync -a --delete` and `.q-system` is not
in `INSTANCE_OWNED_SUBTREES`. What was missing was never the spec, it was a file
at a path the slash menu loads from (ASK-1927).
