#!/bin/bash
set -euo pipefail

# kipi-new-instance.sh - Create a new kipi-system instance
# Usage: ./kipi-new-instance.sh <path> <name>

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REGISTRY="$SCRIPT_DIR/instance-registry.json"
SKELETON_REMOTE="https://github.com/assafkip/kipi-system.git"
SKELETON_BRANCH="main"
PREFIX="q-system"

# Portable in-place sed (BSD/macOS requires `sed -i ''`, GNU/Linux requires `sed -i`)
sed_inplace() {
  if [[ "$(uname)" == "Darwin" ]]; then
    sed -i '' "$@"
  else
    sed -i "$@"
  fi
}

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

# Ensure at least one commit exists (required by git subtree add)
if ! git rev-parse HEAD >/dev/null 2>&1; then
  git commit --allow-empty -m "Initial commit"
fi

# Add subtree
echo "  Adding kipi-system subtree at $PREFIX/..."
git subtree add --prefix="$PREFIX" "$SKELETON_REMOTE" "$SKELETON_BRANCH" --squash
echo "  Subtree added"

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
  sed_inplace "s/{{INSTANCE_NAME}}/$INST_NAME/g" CLAUDE.md 2>/dev/null || true
  echo "  Created template CLAUDE.md"
fi

# Set up .claude/ directory (hooks, rules, agents, output style)
echo "  Setting up .claude/ configuration..."
mkdir -p .claude/agents .claude/output-styles .claude/rules
cp "$SCRIPT_DIR/settings-template.json" .claude/settings.json

# Fix hook paths: subtree nests the repo under q-system/, so q-system/hooks/ becomes q-system/q-system/hooks/
sed_inplace 's|/q-system/hooks/|/q-system/q-system/hooks/|g' .claude/settings.json
sed_inplace 's|/q-system/.q-system/|/q-system/q-system/.q-system/|g' .claude/settings.json

cp "$SCRIPT_DIR"/.claude/agents/*.md .claude/agents/ 2>/dev/null || true
cp "$SCRIPT_DIR"/.claude/output-styles/*.md .claude/output-styles/ 2>/dev/null || true
cp "$SCRIPT_DIR"/.claude/rules/*.md .claude/rules/ 2>/dev/null || true

# Copy root .mcp.json so research-mode (Perplexity) and other MCP servers
# are available at the instance root, where Claude Code looks for .mcp.json
if [ ! -f .mcp.json ] && [ -f "$SCRIPT_DIR/.mcp.json" ]; then
  cp "$SCRIPT_DIR/.mcp.json" .mcp.json
  echo "  Copied .mcp.json (set PERPLEXITY_API_KEY + other tokens in env)"
fi

# Set up plugins (copy contents, not directory, to avoid nesting)
if [ -d "$SCRIPT_DIR/plugins" ]; then
  mkdir -p plugins
  for plugin_dir in "$SCRIPT_DIR"/plugins/*/; do
    if [ -d "$plugin_dir" ]; then
      plugin_name="$(basename "$plugin_dir")"
      cp -R "$plugin_dir" "plugins/$plugin_name"
    fi
  done
fi

# Set up .gitignore (no .githooks - instances should not run skeleton validation)
cp "$SCRIPT_DIR/.gitignore" .gitignore 2>/dev/null || true

echo "  .claude/ configured with rules, agents, and plugins"

# Commit only instance files (never skeleton root files like validate-separation.py, instance-registry.json, kipi-*.sh)
git add "$PREFIX/" .claude/ plugins/ .gitignore CLAUDE.md .mcp.json 2>/dev/null || true
git commit -m "Add kipi-system skeleton as subtree with .claude config"

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
