---
description: Auto-invoke development skills when building skills, plugins, MCP servers, hooks, or using Claude API
paths:
  - "plugins/**"
  - ".claude-plugin/**"
  - ".claude/skills/**"
  - ".claude/agents/**"
  - ".claude/settings.json"
  - "**/*.mcp.json"
  - "**/plugin.json"
  - "**/SKILL.md"
---

# Development Skills Auto-Invocation (ENFORCED)

When building or modifying Claude Code extensions, invoke the matching skill BEFORE writing code.

| Trigger | Skill | What it does |
|---------|-------|-------------|
| Creating or editing a skill (SKILL.md, skill directory) | `skill-creator` | Skill structure, SKILL.md format, best practices |
| Building or modifying an MCP server | `mcp-builder` | MCP server patterns, FastMCP/TypeScript, tool design |
| Building or modifying a Claude Code plugin (plugin.json, marketplace) | `developing-claude-code-plugins` | Plugin lifecycle, manifest, testing, publishing |
| Creating or modifying hooks (settings.json hooks, hook scripts) | `hook-development` | Hook types, event handling, best practices |
| Working with Claude Code config, agents, or features | `working-with-claude-code` | Full Claude Code documentation reference |
| Code that imports `anthropic`, `@anthropic-ai/sdk`, or `claude_agent_sdk` | `claude-api` | Claude API, Anthropic SDK, Agent SDK patterns |

**Rule:** Always invoke the skill first to load its reference material, then write code that follows its patterns.
