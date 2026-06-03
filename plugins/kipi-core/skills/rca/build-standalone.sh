#!/bin/bash
set -euo pipefail
# build-standalone.sh — export the RCA system as a standalone, sellable plugin.
#
# The RCA unit lives inside kipi-core (skills/rca/, the two rca-* commands, and
# the rca hooks in kipi-core/hooks/hooks.json). This script gathers exactly
# those pieces into a self-contained plugin directory with its own plugin.json.
# Internal layout is identical to the bundled version, so ${CLAUDE_PLUGIN_ROOT}
# paths resolve the same way and nothing needs rewriting.
#
# Usage: ./build-standalone.sh [output_dir]
#   default output: plugins/kipi-core/dist/kipi-rca

HERE="$(cd "$(dirname "$0")" && pwd)"   # plugins/kipi-core/skills/rca
CORE="$(cd "$HERE/../.." && pwd)"       # plugins/kipi-core
ROOT="$(cd "$CORE/../.." && pwd)"       # repo root
# Output lives OUTSIDE plugins/ so kipi update's plugin copy never ships the
# build artifact into instances. Override by passing an output dir as $1.
OUT="${1:-$ROOT/dist/kipi-rca}"

mkdir -p "$OUT/skills/rca/references" "$OUT/skills/rca/scripts" "$OUT/commands" "$OUT/hooks"

cp "$HERE/SKILL.md" "$OUT/skills/rca/SKILL.md"
cp "$HERE/references/rca-template.md" "$OUT/skills/rca/references/rca-template.md"
cp "$HERE/scripts/rca-lint.py" "$OUT/skills/rca/scripts/rca-lint.py"
cp "$HERE/scripts/rca-notify.py" "$OUT/skills/rca/scripts/rca-notify.py"
cp "$CORE/commands/rca-start.md" "$OUT/commands/rca-start.md"
cp "$CORE/commands/rca-check.md" "$OUT/commands/rca-check.md"
cp "$CORE/hooks/hooks.json" "$OUT/hooks/hooks.json"
chmod +x "$OUT/skills/rca/scripts/rca-lint.py" "$OUT/skills/rca/scripts/rca-notify.py"

cat > "$OUT/plugin.json" <<'JSON'
{
  "name": "kipi-rca",
  "version": "0.1.0",
  "description": "Root-cause analysis for code. A canonical RCA template, a deterministic structure lint, a command/test-failure notify hook, and /rca-start + /rca-check commands. Separates surface from structural cause, demands evidence-backed verification, tracks checkbox action items, stays blameless. Self-contained, no dependencies.",
  "author": { "name": "Assaf Kipnis" },
  "license": "MIT",
  "skills": "./skills/"
}
JSON

cat > "$OUT/README.md" <<'MD'
# kipi-rca

Root-cause analysis for code, as a Claude Code plugin.

- `/rca-start <slug>` scaffolds an RCA from the canonical template.
- `/rca-check [path]` lints RCA docs against that template.
- The `rca-lint` hook validates any RCA doc on save.
- The `rca-notify` hook taps you to open an RCA when a command or test fails.

The template lives at `skills/rca/references/rca-template.md`. An RCA separates
the surface (trigger) cause from the structural (latent) cause, classifies each
with a type tag, requires evidence-backed verification, tracks action items as
checkboxes, and stays blameless.
MD

echo "built standalone kipi-rca at: $OUT"
find "$OUT" -type f | sort | sed "s#^$OUT/#  #"
