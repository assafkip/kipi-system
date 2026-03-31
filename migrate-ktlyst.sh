#!/usr/bin/env bash
set -euo pipefail

# Migrate KTLYST_strategy data into the kipi plugin instance format.
#
# Usage:
#   bash migrate-ktlyst.sh /path/to/KTLYST_strategy
#
# This script:
#   1. Reads data from a KTLYST_strategy folder
#   2. Finds your kipi plugin data directory automatically
#   3. Creates the instance at ~/.claude/plugins/data/<kipi-dir>/instances/ktlyst/
#   4. Sets ktlyst as the active instance

SRC="${1:-}"

if [ -z "$SRC" ]; then
  echo "Usage: bash migrate-ktlyst.sh /path/to/KTLYST_strategy"
  exit 1
fi

if [ ! -d "$SRC/q-ktlyst" ]; then
  echo "ERROR: $SRC/q-ktlyst not found. Is this a KTLYST_strategy folder?"
  exit 1
fi

# Find the kipi plugin data directory
PLUGIN_BASE="$HOME/.claude/plugins/data"
KIPI_DIR=""
for d in "$PLUGIN_BASE"/kipi-system*; do
  if [ -d "$d" ]; then
    KIPI_DIR="$d"
    break
  fi
done

if [ -z "$KIPI_DIR" ]; then
  echo "ERROR: No kipi-system directory found in $PLUGIN_BASE/"
  echo "Install the plugin first:"
  echo "  /plugin marketplace add assafkip/kipi-system"
  echo "  /plugin install kipi-system@kipi"
  exit 1
fi

DEST="$KIPI_DIR/instances/ktlyst"

if [ -d "$DEST" ]; then
  echo "WARNING: $DEST already exists."
  read -p "Overwrite? (y/N) " confirm
  if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
    echo "Aborted."
    exit 0
  fi
  rm -rf "$DEST"
fi

echo "Source:      $SRC"
echo "Destination: $DEST"
echo ""

echo "Creating instance directory structure..."
mkdir -p "$DEST"/{canonical,marketing/assets,voice,methodology,seed-materials,my-project,memory/{working,weekly,monthly},vc-sourcing,output,bus}

# ── canonical/ ─────────────────────────────────────────────────────
echo "Copying canonical files..."
cp "$SRC/q-ktlyst/canonical/"*.md "$DEST/canonical/" 2>/dev/null || true

# ── marketing/ ─────────────────────────────────────────────────────
echo "Copying marketing files..."
for f in brand-voice.md content-guardrails.md content-themes.md editorial-calendar.md; do
  [ -f "$SRC/q-ktlyst/marketing/$f" ] && cp "$SRC/q-ktlyst/marketing/$f" "$DEST/marketing/"
done
if [ -d "$SRC/q-ktlyst/marketing/assets" ]; then
  cp -r "$SRC/q-ktlyst/marketing/assets/"* "$DEST/marketing/assets/" 2>/dev/null || true
fi
if [ -d "$SRC/q-ktlyst/marketing/templates" ]; then
  cp -r "$SRC/q-ktlyst/marketing/templates" "$DEST/marketing/"
fi

# ── voice/ ─────────────────────────────────────────────────────────
echo "Copying voice files..."
[ -f "$SRC/.claude/skills/founder-voice/references/voice-dna.md" ] && cp "$SRC/.claude/skills/founder-voice/references/voice-dna.md" "$DEST/voice/"
[ -f "$SRC/.claude/skills/founder-voice/references/writing-samples.md" ] && cp "$SRC/.claude/skills/founder-voice/references/writing-samples.md" "$DEST/voice/"

# ── methodology/ ───────────────────────────────────────────────────
echo "Copying methodology files..."
cp "$SRC/q-ktlyst/methodology/"*.md "$DEST/methodology/" 2>/dev/null || true

# ── seed-materials/ ────────────────────────────────────────────────
echo "Copying seed materials..."
cp "$SRC/q-ktlyst/seed-materials/"*.md "$DEST/seed-materials/" 2>/dev/null || true

# ── founder-profile.md ─────────────────────────────────────────────
echo "Copying founder profile..."
if [ -f "$SRC/q-ktlyst/my-project/project-profile.md" ]; then
  cp "$SRC/q-ktlyst/my-project/project-profile.md" "$DEST/founder-profile.md"
fi

# ── AUDHD profile ─────────────────────────────────────────────────
if [ -f "$SRC/.claude/skills/audhd-executive-function/references/user-profile.md" ]; then
  echo "Copying AUDHD profile..."
  mkdir -p "$DEST/audhd"
  cp "$SRC/.claude/skills/audhd-executive-function/references/user-profile.md" "$DEST/audhd/user-profile.md"
fi

# ── my-project/ ────────────────────────────────────────────────────
echo "Copying project data..."
for f in current-state.md competitive-landscape.md relationships.md progress.md notes.md; do
  [ -f "$SRC/q-ktlyst/my-project/$f" ] && cp "$SRC/q-ktlyst/my-project/$f" "$DEST/my-project/"
done

# ── memory/ ────────────────────────────────────────────────────────
echo "Copying memory files..."
for f in graph.jsonl last-handoff.md marketing-state.md morning-state.md evergreen-ideas.md recent-changes.md; do
  [ -f "$SRC/q-ktlyst/memory/$f" ] && cp "$SRC/q-ktlyst/memory/$f" "$DEST/memory/"
done
cp -r "$SRC/q-ktlyst/memory/working/"* "$DEST/memory/working/" 2>/dev/null || true
cp -r "$SRC/q-ktlyst/memory/weekly/"* "$DEST/memory/weekly/" 2>/dev/null || true
cp -r "$SRC/q-ktlyst/memory/monthly/"* "$DEST/memory/monthly/" 2>/dev/null || true

# ── vc-sourcing/ ───────────────────────────────────────────────────
echo "Copying VC sourcing data..."
cp -r "$SRC/q-ktlyst/vc-sourcing/"* "$DEST/vc-sourcing/" 2>/dev/null || true

# ── output/ ────────────────────────────────────────────────────────
echo "Copying output files..."
cp -r "$SRC/q-ktlyst/output/"* "$DEST/output/" 2>/dev/null || true

# ── Set active instance ───────────────────────────────────────────
echo "ktlyst" > "$KIPI_DIR/active-instance"

echo ""
echo "Done!"
echo ""
echo "Instance created at: $DEST"
echo "Active instance set to: ktlyst"
echo ""
echo "File count: $(find "$DEST" -type f | wc -l | tr -d ' ') files"
echo ""
echo "Open Claude Code and run /q-morning to verify."
