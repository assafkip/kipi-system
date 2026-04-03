#!/bin/bash

# kipi-sync-skills.sh - Sync skills from skeleton to subtree instances
# Usage: ./kipi-sync-skills.sh [--dry-run]

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DRY_RUN="${1:-}"

exec python3 "$SCRIPT_DIR/kipi-sync-skills-helper.py" sync "$SCRIPT_DIR" "$DRY_RUN"
