# Agent Pipeline Architecture

Decomposed morning routine into independent agents that communicate via JSON files on disk.
Each agent reads only what it needs, writes results to a shared bus directory, and exits.

## How it works

Instead of one massive Claude Code session doing all morning routine steps sequentially
(burning 100-150K tokens in a single degrading context), the pipeline breaks work into
phases. Each phase spawns focused sub-agents via Claude Code's Agent tool.

Benefits:
- Each agent gets a fresh, small context (2-5K tokens instead of 100K+)
- Step 8 is as sharp as step 1 (no context drift)
- Independent steps run in parallel (faster)
- ~30-50% token reduction vs monolithic approach

## Directory Structure

```
agent-pipeline/
  README.md              - this file
  orchestrator-design.md - phase execution plan (reference doc)
  (review passes defined in .claude/agents/content-reviewer.md)
  bus/                   - inter-agent data exchange (JSON files, per-date subdirectories)
  agents/                - agent prompt files (one per task)
  templates/             - reusable folder structures for repeatable outputs
  agents/step-orchestrator.md  - execution instructions for Claude Code
```

## Key Design Decisions

1. Agents communicate through JSON files in bus/{date}/, not through conversation context
2. Each agent specifies what bus/ files it READS and what bus/ file it WRITES
3. Sonnet for data pulls and checks (cheap, focused). Opus for synthesis and copy generation.
4. `claude -p` subprocess approach does NOT work inside Claude Code (hangs). Use native Agent tool.
5. Bus directories auto-cleaned after 3 days during Phase 0.
6. If pipeline fails, report diagnostics to founder.

## Placeholders

Agent prompts use `{{PLACEHOLDER}}` syntax for project-specific values.
See `PLACEHOLDERS.md` for the full list of 26 placeholders, what they mean,
default values, and where to fill them in.

## Customization

Agent prompts in agents/ are generic. To customize for your project:
1. Update agent prompts with your specific MCP servers, Notion DB IDs, API endpoints
2. Add/remove agents for phases that don't apply to your workflow
3. Adjust model allocation in step-orchestrator.md (sonnet vs opus per agent)
4. Add your canonical file paths to compliance/positioning check agents
