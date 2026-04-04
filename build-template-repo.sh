#!/bin/bash
set -euo pipefail

# Build a clean template repo for new (non-technical) users to fork
# This strips out admin tools, personal data, and skeleton management files
# Output: template-repo/ directory ready to push to GitHub as a template

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TEMPLATE_DIR="$SCRIPT_DIR/template-repo"

echo "Building template repo..."

# Clean previous build
rm -rf "$TEMPLATE_DIR"
mkdir -p "$TEMPLATE_DIR"

# 1. Copy the q-system skeleton (the core OS)
cp -R "$SCRIPT_DIR/q-system" "$TEMPLATE_DIR/q-system"

# 2. Copy .claude directory (skills, rules, settings template)
cp -R "$SCRIPT_DIR/.claude" "$TEMPLATE_DIR/.claude"
# Remove local settings (has real tokens)
rm -f "$TEMPLATE_DIR/.claude/settings.local.json"
# Replace settings.json with template version
cp "$SCRIPT_DIR/settings-template.json" "$TEMPLATE_DIR/.claude/settings.json"

# 3. Copy marketplace manifest and plugins
cp -R "$SCRIPT_DIR/.claude-plugin" "$TEMPLATE_DIR/.claude-plugin"
cp -R "$SCRIPT_DIR/plugins" "$TEMPLATE_DIR/plugins"

# 4. Copy memory directory structure (empty)
mkdir -p "$TEMPLATE_DIR/memory"
touch "$TEMPLATE_DIR/memory/.gitkeep"

# 5. Create the template .mcp.json (empty - built during onboarding)
cat > "$TEMPLATE_DIR/.mcp.json" << 'EOF'
{
  "mcpServers": {}
}
EOF

# 6. Create the template CLAUDE.md
cat > "$TEMPLATE_DIR/CLAUDE.md" << 'EOF'
# My Project

## About
A personal operating system powered by Kipi.

## Entrepreneur OS
@q-system/CLAUDE.md

## Instance Rules
(Your project-specific rules will be added here during setup)
EOF

# 7. Copy .gitignore
cp "$SCRIPT_DIR/.gitignore" "$TEMPLATE_DIR/.gitignore"

# 8. Create the user-facing README
cp "$SCRIPT_DIR/q-system/.q-system/onboarding/GETTING-STARTED.md" "$TEMPLATE_DIR/README.md"

# 9. Clean any .DS_Store files
find "$TEMPLATE_DIR" -name ".DS_Store" -delete

# 11. Ensure output directories exist with .gitkeep
mkdir -p "$TEMPLATE_DIR/q-system/output/drafts"
mkdir -p "$TEMPLATE_DIR/q-system/output/lead-gen"
mkdir -p "$TEMPLATE_DIR/q-system/output/design-partner"
mkdir -p "$TEMPLATE_DIR/q-system/output/marketing/linkedin"
touch "$TEMPLATE_DIR/q-system/output/.gitkeep"
touch "$TEMPLATE_DIR/q-system/output/drafts/.gitkeep"
touch "$TEMPLATE_DIR/q-system/output/lead-gen/.gitkeep"
touch "$TEMPLATE_DIR/q-system/output/design-partner/.gitkeep"
touch "$TEMPLATE_DIR/q-system/output/marketing/linkedin/.gitkeep"

# 12. Ensure memory structure exists
mkdir -p "$TEMPLATE_DIR/q-system/memory/working"
mkdir -p "$TEMPLATE_DIR/q-system/memory/weekly"
mkdir -p "$TEMPLATE_DIR/q-system/memory/monthly"
touch "$TEMPLATE_DIR/q-system/memory/working/.gitkeep"
touch "$TEMPLATE_DIR/q-system/memory/weekly/.gitkeep"
touch "$TEMPLATE_DIR/q-system/memory/monthly/.gitkeep"

echo ""
echo "Template repo built at: $TEMPLATE_DIR"
echo ""
echo "Contents:"
find "$TEMPLATE_DIR" -type f | wc -l
echo " files"
echo ""
echo "Next steps:"
echo "  1. Review the template: ls -la $TEMPLATE_DIR"
echo "  2. Create a GitHub repo and push:"
echo "     cd $TEMPLATE_DIR && git init && git add -A && git commit -m 'Initial template'"
echo "     gh repo create kipi-template --private --source=. --push"
echo "  3. Go to GitHub repo settings and check 'Template repository'"
echo "  4. Share the repo link with users"
