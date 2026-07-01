#!/bin/bash
set -euo pipefail

# kipi-new-instance.sh - Create a new kipi-system instance
# Usage: ./kipi-new-instance.sh <path> <name>

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REGISTRY="$SCRIPT_DIR/instance-registry.json"
SKELETON_REMOTE="https://github.com/assafkip/kipi-system.git"
SKELETON_BRANCH="main"
PREFIX="q-system"

if [ $# -lt 2 ]; then
  echo "Usage: $0 <path> <name>"
  echo "  path: directory to create the instance in"
  echo "  name: short name for the instance (e.g., my-startup)"
  exit 1
fi

INST_PATH="$1"
INST_NAME="$2"

if [ -d "$INST_PATH/$PREFIX" ]; then
  echo "ERROR: $INST_PATH/$PREFIX already exists. Aborting."
  exit 1
fi

echo "=== Creating new kipi instance ==="
echo "  Path: $INST_PATH"
echo "  Name: $INST_NAME"
echo ""

# Create directory if needed
mkdir -p "$INST_PATH"
cd "$INST_PATH"

# Init git if needed
if [ ! -d .git ]; then
  git init
  echo "  Initialized git repo"
fi

# Ensure at least one commit exists
if ! git rev-parse HEAD >/dev/null 2>&1; then
  git commit --allow-empty -m "Initial commit"
fi

# Seed $PREFIX/ with the skeleton's q-system/ CONTENT only (same layout kipi-update.sh
# maintains). The old `git subtree add` put the ENTIRE skeleton repo under $PREFIX/
# (root scripts, README, plugins/, plus a nested q-system/q-system/ shadow tree that
# included a snapshot of the skeleton's own memory/). Every instance created that way
# carried 30-350 stale junk files the updater could never delete. Scar: fleet cleanup
# 2026-07-01 removed the shadow trees from 18/19 instances.
echo "  Seeding $PREFIX/ from skeleton q-system/ (git archive)..."
mkdir -p "$PREFIX"
git -C "$SCRIPT_DIR" archive --format=tar HEAD -- q-system/ | tar -x --strip-components=1 -C "$PREFIX"
echo "  Skeleton q-system content seeded"

# Create instance CLAUDE.md
if [ ! -f CLAUDE.md ]; then
  cat > CLAUDE.md << 'CLAUDE_EOF'
# {{INSTANCE_NAME}}

## About
{{DESCRIPTION}}

## Entrepreneur OS
@q-system/CLAUDE.md

## Conventions
- Never produce fluff - every sentence must carry information or enable action
- Mark unvalidated claims with `{{UNVALIDATED}}` or `{{NEEDS_PROOF}}`
CLAUDE_EOF
  sed -i '' "s/{{INSTANCE_NAME}}/$INST_NAME/g" CLAUDE.md 2>/dev/null || true
  echo "  Created template CLAUDE.md"
fi

# Set up .claude/ directory (hooks, rules, agents, output style)
echo "  Setting up .claude/ configuration..."
mkdir -p .claude/agents .claude/output-styles .claude/rules
cp "$SCRIPT_DIR/settings-template.json" .claude/settings.json

# No hook-path rewriting: the archive seeding above puts skeleton q-system/ CONTENT
# at $PREFIX/, so template paths like q-system/.q-system/scripts/X.py are already
# correct. The old sed doubling to q-system/q-system/ matched the old subtree layout
# and produced dead hook paths after the first kipi update flattened it.

cp "$SCRIPT_DIR"/.claude/agents/*.md .claude/agents/ 2>/dev/null || true
cp "$SCRIPT_DIR"/.claude/output-styles/*.md .claude/output-styles/ 2>/dev/null || true
cp "$SCRIPT_DIR"/.claude/rules/*.md .claude/rules/ 2>/dev/null || true

# Copy root .mcp.json so research-mode (Perplexity) and other MCP servers
# are available at the instance root, where Claude Code looks for .mcp.json
if [ ! -f .mcp.json ] && [ -f "$SCRIPT_DIR/.mcp.json" ]; then
  cp "$SCRIPT_DIR/.mcp.json" .mcp.json
  echo "  Copied .mcp.json (set PERPLEXITY_API_KEY + other tokens in env)"
fi

# Set up plugins (copy contents, not directory, to avoid nesting).
# rsync, not cp -R: a symlinked skeleton plugin (memory-lifecycle -> standalone repo)
# would otherwise materialize WITH its .git, leaving the instance permanently dirty
# on plugins/<name> in git status. Mirrors kipi-update.sh.
if [ -d "$SCRIPT_DIR/plugins" ]; then
  mkdir -p plugins
  for plugin_dir in "$SCRIPT_DIR"/plugins/*/; do
    if [ -d "$plugin_dir" ]; then
      plugin_name="$(basename "$plugin_dir")"
      rsync -a --exclude="/.git/" --exclude="__pycache__/" --exclude="*.pyc" \
        "$plugin_dir" "plugins/$plugin_name/"
    fi
  done
fi

# Set up .gitignore (no .githooks - instances should not run skeleton validation)
cp "$SCRIPT_DIR/.gitignore" .gitignore 2>/dev/null || true

echo "  .claude/ configured with rules, agents, and plugins"

# Commit only instance files (never skeleton root files like validate-separation.py, instance-registry.json, kipi-*.sh)
git add "$PREFIX/" .claude/ plugins/ .gitignore CLAUDE.md .mcp.json 2>/dev/null || true
git commit -m "Seed kipi-system q-system content with .claude config"

# Register in instance-registry.json
echo "  Registering in instance-registry.json..."
python3 -c "
import json
reg = json.load(open('$REGISTRY'))
entry = {
    'name': '$INST_NAME',
    'path': '$(cd "$INST_PATH" && pwd)',
    'subtree_prefix': '$PREFIX',
    'instance_q_dir': None,
    'type': 'subtree',
    'has_git': True
}
# Check if already registered
names = [i['name'] for i in reg['instances']]
if '$INST_NAME' not in names:
    reg['instances'].append(entry)
    json.dump(reg, open('$REGISTRY', 'w'), indent=2)
    print('  Registered')
else:
    print('  Already registered')
"

echo ""
echo "=== Done ==="
echo "Instance created at $INST_PATH"
echo "Next: edit CLAUDE.md to add your project details, then run the setup wizard."
