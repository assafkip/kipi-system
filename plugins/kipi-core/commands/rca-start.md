---
description: Scaffold a new RCA document from the canonical template, ready to fill.
allowed-tools: Bash, Read, Write
---

Start a root-cause analysis. The author gives a short slug for the failure (e.g.
`drawer-empty-code`). Default the slug to `untitled` if none is given.

## Process

1. Read the canonical structure from
   `${CLAUDE_PLUGIN_ROOT}/skills/rca/references/rca-template.md`.

2. Resolve the output path. Inside a kipi instance use
   `q-system/output/rca/`; in a plain repo use `rca/`. Create the directory:

```bash
DIR="q-system/output/rca"; [ -d q-system ] || DIR="rca"; mkdir -p "$DIR"; echo "RCA dir: $DIR"; date +%F
```

3. Write `<DIR>/rca-<slug>-<YYYY-MM-DD>.md` using the required structure from the
   template: metadata (Date, Trigger, Surface-fix commit, Structural-fix commit)
   and every required `##` section. Pre-fill Date and anything already known from
   context. Leave the rest as clearly-marked placeholders.

4. Tell the author the file path and that `/rca-check <path>` lints it. Do not
   fill causes or verification you do not actually have; an honest empty section
   beats an invented one.

The `rca-lint` hook will validate the file on save. Surface its output verbatim
if it blocks.
