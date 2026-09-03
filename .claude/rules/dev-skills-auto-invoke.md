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

**Scope of (ENFORCED) above: the trigger table, held by `q-system/.q-system/scripts/dev-skills-lint.py`.** Run by `kipi check` (`validate-separation.py` Gate 1.1c) and pinned by `q-system/.q-system/scripts/test/test-dev-skills-lint.py`. It exits 2 when a row below names a skill with no readable `SKILL.md` anywhere, when the table is gone, or when a skill cell carries no backticked name -- so the rule can never quietly point at a skill that is not installed.

Read its silence narrowly, two ways. A skill resolving on disk is not proof the running session offers it (plugin enablement is marketplace state this repo does not own; measured 2026-08-22, all six rows resolved while three were absent from that session's skill listing). And whether you actually INVOKE the skill is a model decision no script can observe -- a validator sees the table, never the skill you skipped. That half is measured advisory-only against `q-system/.q-system/skill-evals/dev-skills-auto-invoke.json` by `skill-trigger-eval.py`, the same posture `skill-hook-pairing.md` already gives founder-voice, rca and fable-discipline.

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
