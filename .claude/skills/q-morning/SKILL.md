---
name: q-morning
description: "Run the full morning routine pipeline. 9 phases, 25 agents, produces a daily HTML action plan. Use when the user says 'morning', 'q-morning', 'daily routine', 'start my day', or 'what should I do today'."
user-invocable: true
---

# Morning Routine Pipeline

**STOP. Do not execute from this prompt. Read the orchestrator first.**

If you read this skill prompt and feel like you know what to do - you don't.
The orchestrator contains mandatory reads (preflight guardrails, known issues,
execution gates) that prevent you from re-discovering bugs. Every session that
skipped the reads broke the same things.

## Instructions

1. Read the orchestrator: `q-system/.q-system/steps/step-orchestrator.md`
2. **The orchestrator has a MANDATORY READS section at the top. Complete those reads before Phase 0.**
3. Follow the orchestrator exactly. It defines 9 phases of sub-agent execution.
4. Replace template variables:
   - `{{DATE}}` = today's date (YYYY-MM-DD)
   - `{{BUS_DIR}}` = `q-system/.q-system/agent-pipeline/bus/{date}`
   - `{{AGENTS_DIR}}` = `q-system/.q-system/agent-pipeline/agents`
   - `{{QROOT}}` = `q-system`
5. Spawn sub-agents per phase using the Agent tool with each agent's prompt file.
6. After Phase 8 (build), run the audit:
   ```bash
   python3 q-system/.q-system/bus-to-log.py {date}
   python3 q-system/.q-system/audit-morning.py q-system/output/morning-log-{date}.json
   ```
7. Show the audit output to the founder.

## Key Rules
- Do NOT read commands.md or preflight.md in full (token discipline)
- Do NOT skip steps to save context. Tell the founder if context is low.
- If Apify fails, auto-fallback to Chrome (do not ask)
- Bus files are overwritten each run, never appended
- Notion: use `mcp__notion_api__*` tools with data_source_id (full UUID) from `q-system/my-project/notion-ids.md`
