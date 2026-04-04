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
  sed -i '' "s/{{INSTANCE_NAME}}/$INST_NAME/g" CLAUDE.md 2>/dev/null || true
  echo "  Created template CLAUDE.md"
fi

# Set up .claude/ directory (hooks, rules, agents, output style)
echo "  Setting up .claude/ configuration..."
mkdir -p .claude/agents .claude/output-styles .claude/rules
cp "$SCRIPT_DIR/settings-template.json" .claude/settings.json

# Fix hook paths: subtree nests the repo under q-system/, so q-system/hooks/ becomes q-system/q-system/hooks/
sed -i '' 's|/q-system/hooks/|/q-system/q-system/hooks/|g' .claude/settings.json
sed -i '' 's|/q-system/.q-system/|/q-system/q-system/.q-system/|g' .claude/settings.json

cp "$SCRIPT_DIR"/.claude/agents/*.md .claude/agents/ 2>/dev/null || true
cp "$SCRIPT_DIR"/.claude/output-styles/*.md .claude/output-styles/ 2>/dev/null || true
cp "$SCRIPT_DIR"/.claude/rules/*.md .claude/rules/ 2>/dev/null || true

# Set up marketplace plugins
cp -R "$SCRIPT_DIR/.claude-plugin" .claude-plugin 2>/dev/null || true
cp -R "$SCRIPT_DIR/plugins" plugins 2>/dev/null || true

# Set up .gitignore
cp "$SCRIPT_DIR/.gitignore" .gitignore 2>/dev/null || true

echo "  .claude/ configured with hooks, rules, agents, and plugins"

# Commit
git add -A
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
