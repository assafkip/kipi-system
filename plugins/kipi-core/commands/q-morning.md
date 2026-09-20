---
description: The day brief: calendar, the mail needing an answer, the consulting board. Runs the 07:40 job early.
allowed-tools: Bash, Read
---

Run the morning brief now instead of waiting for it.

The live path is the launchd job `com.kipi.morning-brief`, which fires at 07:40.
This command runs the same script early. It is not a second implementation.

```bash
QROOT="q-system"; [ -d "$QROOT" ] || QROOT="."; echo "QROOT: $QROOT"
```

```bash
python3 "$QROOT/.q-system/scripts/morning-brief.py"
```

A section that could not be read says COULD NOT READ, never "nothing". An empty
section and an unreachable one are different facts and the brief must not merge
them.

What is owed today and which overnight jobs failed are COLLECTED and do not reach
the founder: they are engineering signal and route to Sana's Linear triage
(`.claude/rules/founder-notifications.md`, 2026-08-10).

If no brief lands by 09:00, `com.kipi.morning-brief-deadman` says so. The 9-phase
agent pipeline this replaced is RETIRED (`canonical/decisions.md`
RULE-2026-08-30-A); do not restart it.

The canonical spec is the `/q-morning` entry in `q-system/.q-system/commands.md`.
Read it there and follow it; this file does not restate it, so it cannot drift
from it. That spec already reaches every instance -- `kipi-update.sh` copies
`git archive HEAD -- q-system/` with `rsync -a --delete` and `.q-system` is not
in `INSTANCE_OWNED_SUBTREES`. What was missing was never the spec, it was a file
at a path the slash menu loads from (ASK-1927).
