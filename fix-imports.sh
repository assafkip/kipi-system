#!/bin/bash
set -euo pipefail

# Portable in-place sed (BSD/macOS requires `sed -i ''`, GNU/Linux requires `sed -i`)
sed_inplace() {
  if [[ "$(uname)" == "Darwin" ]]; then
    sed -i '' "$@"
  else
    sed -i "$@"
  fi
}

for f in \
  ~/Desktop/ktlyst-hub/strategy/CLAUDE.md \
  ~/Desktop/ktlyst-hub/product/CLAUDE.md \
  ~/Desktop/ASK_AI_consultant/CLAUDE.md \
  ~/Desktop/ktlyst-hub/website/CLAUDE.md \
  ~/Desktop/4_points_consulting/CLAUDE.md \
  ~/Desktop/ktlyst-hub/lawyer/CLAUDE.md
do
  if [ -f "$f" ]; then
    sed_inplace 's|@q-system/q-system/CLAUDE.md|@q-system/CLAUDE.md|g' "$f"
    echo "fixed: $f"
  else
    echo "skip: $f"
  fi
done

echo "done"
