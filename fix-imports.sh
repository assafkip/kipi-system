#!/bin/bash
set -euo pipefail

for f in \
  ~/Desktop/ktlyst-hub/strategy/CLAUDE.md \
  ~/Desktop/ktlyst-hub/product/CLAUDE.md \
  ~/Desktop/ASK_AI_consultant/CLAUDE.md \
  ~/Desktop/ktlyst-hub/website/CLAUDE.md \
  ~/Desktop/client_a/CLAUDE.md \
  ~/Desktop/ktlyst-hub/lawyer/CLAUDE.md
do
  if [ -f "$f" ]; then
    sed -i '' 's|@q-system/q-system/CLAUDE.md|@q-system/CLAUDE.md|g' "$f"
    echo "fixed: $f"
  else
    echo "skip: $f"
  fi
done

echo "done"
