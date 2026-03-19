#!/bin/bash
# Tool availability diagnostic
# Called by UserPromptSubmit hook before scoping/planning commands.
# Checks which MCP servers, API keys, and CLI tools are available.

echo "=== Tool Availability Check ==="

# MCP servers (check if configured in settings)
echo ""
echo "MCP Servers:"
for server in notion_api apify threat-intel osint-infra; do
  if grep -q "\"$server\"" "$CLAUDE_PROJECT_DIR/.claude/settings.json" 2>/dev/null || \
     grep -q "\"$server\"" "$CLAUDE_PROJECT_DIR/.mcp.json" 2>/dev/null || \
     grep -q "\"$server\"" "$HOME/.claude/settings.json" 2>/dev/null; then
    echo "  [OK] $server configured"
  else
    echo "  [--] $server not configured"
  fi
done

# API keys (check env vars, don't print values)
echo ""
echo "API Keys:"
for key in NOTION_TOKEN APIFY_TOKEN VIRUSTOTAL_API_KEY ABUSECH_AUTH_KEY; do
  if [ -n "${!key}" ]; then
    echo "  [OK] $key set"
  else
    echo "  [--] $key not set"
  fi
done

# CLI tools
echo ""
echo "CLI Tools:"
for tool in whois dig nslookup curl jq python3 uv node npx; do
  if command -v "$tool" &>/dev/null; then
    echo "  [OK] $tool"
  else
    echo "  [--] $tool not found"
  fi
done

# Chrome MCP (check if extension is likely running)
echo ""
echo "Browser:"
if pgrep -f "Google Chrome" &>/dev/null; then
  echo "  [OK] Chrome running"
else
  echo "  [--] Chrome not running"
fi

echo ""
echo "=== Done ==="
