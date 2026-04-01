---
description: "Token discipline — self-monitoring rules, retry limits, agent spawn guards"
user-invocable: false
paths:
  - "**/*"
---

# Token Discipline

**Gate check:** Read `{config_dir}/enabled-integrations.md`. If `token-discipline` is `false`, SKIP this rule file.


When the token-guard hook blocks you (exit 2 message), follow its instructions exactly.
Do not attempt to work around the block. The block exists because you are burning
tokens without results.

Common blocks and what to do:
- "3 retries": Something is broken. Diagnose the root cause. Tell the founder.
- "50 tool calls": You've been working too long without checking in. Summarize progress.
- "3 subagents": Use Grep/Glob/Read directly. Agents are expensive.
- "30 MCP calls": You're hammering an API. Batch your requests or reduce scope.
- "15 reads without write": You're exploring, not producing. Pick a direction.

Self-monitoring rules (Layer 2, always active even without hook triggers):
- If a tool call fails, do NOT retry the same call. Diagnose why it failed first. Change the approach.
- After 10 tool calls, pause and check: "Am I closer to the goal than 10 calls ago?" If not, stop and tell the founder.
- Never spawn an Explore/research agent for something a single Grep or Glob could answer.
- Before spawning any Agent, ask: "Is this worth 50K+ tokens?" If the answer is "maybe," use direct tools instead.
- If you've read 5+ files without writing anything, stop and tell the founder what you're looking for and why.
- Never hold large API responses in context. Process and discard immediately.
- When blocked, do NOT brute-force. Try a different approach or ask the founder.
