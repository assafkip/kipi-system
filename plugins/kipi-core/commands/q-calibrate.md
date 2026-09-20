---
description: Update canonical files from new information, feedback, or a market change. Ripple check enforced.
argument-hint: [what changed]
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

Enter CALIBRATE mode and update the canonical files.

`$ARGUMENTS` is what changed. If empty, ask once what moved, then proceed.

```bash
QROOT="q-system"; [ -d "$QROOT" ] || QROOT="."; echo "QROOT: $QROOT"
```

Read the **Post-Edit Ripple Check** section of that same file too. Two gates are
not optional here:

1. A significant change (positioning, strategy, messaging; more than 5 lines or a
   new section) runs a Quick Council FIRST. If 2+ personas object, surface the
   dissent before writing (`.claude/rules/auto-detection.md`). A typo, a date, or
   a data point added to an existing section skips it.
2. Every decision written to `canonical/decisions.md` carries an origin tag
   (`.claude/rules/sycophancy-core.md`). No untagged rows.

Then log the edit and verify the ripple:

```bash
python3 "$QROOT/.q-system/scripts/ripple-verify.py" "$QROOT/canonical/changelog.md" "$(date +%F)"
```

Exit 1 from the verifier is a soft gate: address the missing targets, or log a
skip reason in the changelog.

The canonical spec is the `/q-calibrate` entry in `q-system/.q-system/commands.md`.
Read it there and follow it; this file does not restate it, so it cannot drift
from it. That spec already reaches every instance -- `kipi-update.sh` copies
`git archive HEAD -- q-system/` with `rsync -a --delete` and `.q-system` is not
in `INSTANCE_OWNED_SUBTREES`. What was missing was never the spec, it was a file
at a path the slash menu loads from (ASK-1927).
