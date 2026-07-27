#!/bin/bash
set -euo pipefail

# instance-diet-fix.sh - Fix broken imports and remove duplicate sections
# from an instance's CLAUDE.md. Creates a backup before modifying.
#
# Usage: ./instance-diet-fix.sh [instance-path]
#        If no path given, uses current directory.
#
# What it fixes:
# 1. Broken @q-system/q-system/CLAUDE.md import -> @q-system/CLAUDE.md
# 2. Removes sections duplicated by skeleton rules:
#    - Tech Stack (auto-discovered)
#    - Project Structure (folder-structure.md rule)
#    - Tool Preferences (coded in rules/settings)
#    - ADHD-Aware Interaction Rules (audhd-interaction.md rule)
#    - Formatting Rules (founder output style)
#    - Operating Modes (methodology/modes.md)
#    - Token Discipline (token-discipline.md rule)
#    - MCP Servers Available (auto-discovered)

INST="${1:-.}"
CLAUDE_MD="$INST/CLAUDE.md"

if [ ! -f "$CLAUDE_MD" ]; then
  echo "ERROR: $CLAUDE_MD not found"
  exit 1
fi

echo "=== Instance Diet Fix: $(basename "$(cd "$INST" && pwd)") ==="
echo ""

# Backup
cp "$CLAUDE_MD" "$CLAUDE_MD.bak"
echo "Backup: $CLAUDE_MD.bak"

# Count before
BEFORE=$(grep -c '.' "$CLAUDE_MD" || true)

# Fix broken import path
if grep -q '@q-system/q-system/CLAUDE.md' "$CLAUDE_MD"; then
  sed -i '' 's|@q-system/q-system/CLAUDE.md|@q-system/CLAUDE.md|g' "$CLAUDE_MD"
  echo "Fixed: broken import @q-system/q-system/CLAUDE.md -> @q-system/CLAUDE.md"
fi

# Remove duplicate sections using python (sed can't do multiline section removal reliably)
python3 - "$CLAUDE_MD" << 'PYEOF'
import re, sys

path = sys.argv[1]
with open(path) as f:
    content = f.read()

# Sections to remove (case-insensitive header match)
remove_headers = [
    r"## Tech Stack",
    r"## Project Structure",
    r"## Tool Preferences",
    r"## ADHD-Aware Interaction Rules.*",
    r"## Formatting Rules",
    r"## Operating Modes",
    r"## Token Discipline.*",
    r"## MCP Servers Available",
]

for header_pat in remove_headers:
    # Match from ## Header to next ## or end of file
    pattern = rf"(?m)^{header_pat}\n[\s\S]*?(?=\n## |\Z)"
    match = re.search(pattern, content)
    if match:
        removed = match.group(0).splitlines()[0]
        content = content[:match.start()] + content[match.end():]
        print(f"Removed: {removed}")

# Clean up multiple blank lines
content = re.sub(r"\n{3,}", "\n\n", content).strip() + "\n"

with open(path, "w") as f:
    f.write(content)
PYEOF

# Count after
AFTER=$(grep -c '.' "$CLAUDE_MD" || true)
SAVED=$((BEFORE - AFTER))

echo ""
echo "Before: $BEFORE lines"
echo "After:  $AFTER lines"
echo "Saved:  $SAVED lines"

# Run budget audit if available
AUDIT="$INST/q-system/.q-system/scripts/instruction-budget-audit.py"
if [ -f "$AUDIT" ]; then
  echo ""
  echo "--- Budget Check ---"
  python3 "$AUDIT" || true
fi
