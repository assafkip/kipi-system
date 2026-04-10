---
description: Token consumption guardrails and self-monitoring rules
paths:
  - "**/*"
---

# Token Discipline

When the token-guard hook blocks you (exit 2 message), follow its instructions exactly.
Do not attempt to work around the block. The block exists because you are burning
tokens without results.

Common blocks and what to do:
- "3 retries": Something is broken. Diagnose the root cause. Tell the founder.
- "50 tool calls": You've been working too long without checking in. Summarize progress.
- "25 subagents": Use Grep/Glob/Read directly. Agents are expensive.
- "30 MCP calls": You're hammering an API. Batch your requests or reduce scope.
- "15 reads without write": You're exploring, not producing. Pick a direction.
- "read [file] N times": You already have this info. Extract what you need and move on.
- "N searches without output": You're grep-drifting. Pick the best result and write something.
- "N edit attempts on [file]": Your edit approach is wrong. Read the file again, find the exact match, or ask the founder.
- "N agents no output": Agents aren't helping. Use Grep/Glob/Read directly.
- "N minutes since last write": You may be stuck. Summarize what you've tried and what's blocking you.

Self-monitoring rules (Layer 2, always active even without hook triggers):
- If a tool call fails, do NOT retry the same call. Diagnose why it failed first. Change the approach.
- After 10 tool calls, pause and check: "Am I closer to the goal than 10 calls ago?" If not, stop and tell the founder.
- Never spawn an Explore/research agent for something a single Grep or Glob could answer.
- Before spawning any Agent, ask: "Is this worth 50K+ tokens?" If the answer is "maybe," use direct tools instead.
- If you've read 5+ files without writing anything, stop and tell the founder what you're looking for and why.
- Never hold large API responses in context. Process and discard immediately.
- When blocked, do NOT brute-force. Try a different approach or ask the founder.

## Cleanup / Migration Rule (ENFORCED)

When doing cleanup, migration, or rename tasks: run TWO grep passes.
- Pass 1 catches obvious string/symbol hits.
- Pass 2 catches stale IDs, dead import paths, and embedded references in JSON, HTML, and markdown.
- State "pass 1 done, starting pass 2" before finishing.
- Not optional, even on small renames.

## Pre-Action Echo (ENFORCED)

Before the first Edit, Write, or destructive Bash call: if the task touches more than one file OR more than one tool category (Read, Bash, Edit, Web, Agent), echo the plan in 2-3 bullets and wait for OK. No exceptions for "small" tasks. If you find yourself thinking "this is small, I'll just do it," that is the trigger to echo.

**Exception:** Does not apply to agent pipeline sub-agents executing inside `/q-morning`. Pipeline phases run autonomously.
