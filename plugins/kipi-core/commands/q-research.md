---
description: Anti-hallucination research mode: every claim cites a source, through a 4-level cascade, on a token budget.
argument-hint: [topic]
allowed-tools: Bash, Read, Write, Glob, Grep, WebSearch, WebFetch
---

Enter research mode on `$ARGUMENTS`.

This command loads the `research-mode` skill in this plugin
(`plugins/kipi-core/skills/research-mode/`). A copy of this file used to sit at
`plugins/kipi-core/skills/research-mode/commands/q-research.md`, which is NOT a
load path: Claude Code discovers a plugin's `commands/` directory at the plugin
root only. That file was inert and `/q-research` was absent from the session
command list while `kipi-core:say` and `kipi-core:wiring-check` were present
(measured 2026-09-20, ASK-1927).

```bash
QROOT="q-system"; [ -d "$QROOT" ] || QROOT="."; echo "QROOT: $QROOT"
```

Read `$QROOT/methodology/anti-hallucination.md` and the research-mode SKILL.md,
then work the cascade in order: local files first, then search snippets, then a
full page fetch, then Scholar Gateway. Budget is 5 searches and 3 fetches per
question.

Every claim cites its source. "I don't know" is a correct answer here and is the
point of the mode. An unsourced claim gets `{{UNVALIDATED}}` or `{{NEEDS_PROOF}}`
rather than confident prose (`q-system/CLAUDE.md`).

Say "exit research mode" to return to normal.

The canonical spec is the `/q-research [topic]` section of `q-system/.q-system/commands.md`.
Read it there and follow it; this file does not restate it, so it cannot drift
from it. That spec already reaches every instance -- `kipi-update.sh` copies
`git archive HEAD -- q-system/` with `rsync -a --delete` and `.q-system` is not
in `INSTANCE_OWNED_SUBTREES`. What was missing was never the spec, it was a file
at a path the slash menu loads from (ASK-1927).
