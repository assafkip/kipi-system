#!/usr/bin/env bash
# export-fable-mirror.sh — de-kipi'd export of the fable-discipline skill
# (prd-os's execution-discipline layer) to the public mirror repo
# github.com/assafkip/fable-discipline. Founder decision 2026-07-03: the
# public repo MIRRORS the merged version; this script is the mechanism and
# its --check mode is the executable drift blocker (required_check on every
# discipline-layer issue of prd-fable-discipline-2026-07-04).
#
# Modes:
#   (default)  export: write the transformed skill files into the local mirror
#              clone. NEVER pushes — the founder reviews and pushes under
#              their own gh auth.
#   --check    diff-only: exit 0 when the mirror clone matches a fresh export,
#              exit 2 on divergence, exit 2 (loud, not skip) when the clone is
#              missing. A silent skip-if-absent would be a prompt-only gate.
#
# Managed surface (only these paths are written/compared; README, LICENSE,
# llms.txt, .claude-plugin/, hooks/ are public-repo-owned):
#   skills/fable-discipline/SKILL.md
#   skills/fable-discipline/EXAMPLE.md
#   skills/fable-discipline/references/checklist.md
#   skills/fable-discipline/scripts/fable-discipline-lint.py
#   skills/fable-discipline/scripts/test_fable_discipline_lint.py
#
# De-kipi transform: strips <!-- kipi-only:start --> .. <!-- kipi-only:end -->
# blocks from markdown. Kipi-internal prose MUST live inside those markers;
# that keeps the transform deterministic instead of a hand-maintained diff.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
SRC="$REPO_ROOT/plugins/prd-os/skills/fable-discipline"
MIRROR="${FABLE_MIRROR_DIR:-$HOME/projects/fable-discipline}"
DEST="$MIRROR/skills/fable-discipline"

FILES=(
  "SKILL.md"
  "EXAMPLE.md"
  "references/checklist.md"
  "scripts/fable-discipline-lint.py"
  "scripts/test_fable_discipline_lint.py"
)

if [ ! -d "$MIRROR/.git" ]; then
  echo "FAIL: mirror clone not found at $MIRROR" >&2
  echo "Run: gh repo clone assafkip/fable-discipline $MIRROR (or set FABLE_MIRROR_DIR)" >&2
  exit 2
fi

strip_kipi_only() {
  # remove kipi-only blocks (inclusive) from markdown; pass code through as-is
  case "$1" in
    *.md) sed '/<!-- kipi-only:start -->/,/<!-- kipi-only:end -->/d' "$1" ;;
    *) cat "$1" ;;
  esac
}

STAGE="$(mktemp -d)"
trap 'rm -r "$STAGE"' EXIT

for f in "${FILES[@]}"; do
  mkdir -p "$STAGE/$(dirname "$f")"
  strip_kipi_only "$SRC/$f" > "$STAGE/$f"
done

if [ "${1:-}" = "--check" ]; then
  status=0
  for f in "${FILES[@]}"; do
    if ! diff -u "$STAGE/$f" "$DEST/$f" >/dev/null 2>&1; then
      echo "DRIFT: $f differs between export and mirror clone" >&2
      status=2
    fi
  done
  [ "$status" -eq 0 ] && echo "mirror check: clean ($MIRROR)"
  exit "$status"
fi

for f in "${FILES[@]}"; do
  mkdir -p "$DEST/$(dirname "$f")"
  cp "$STAGE/$f" "$DEST/$f"
done
echo "exported to $DEST — review and push from $MIRROR (script never pushes)"
