---
description: Token consumption guardrails and self-monitoring rules
paths:
  - "**/*"
---

# Token Discipline

The executable is `q-system/.q-system/token-guard.py`, wired PreToolUse + PostToolUse +
UserPromptSubmit in BOTH `.claude/settings.json` and `settings-template.json`. Layer 1
below IS that script. When it blocks you (exit 2), follow it; do not work around it.

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
- **Scope of (ENFORCED) above:** only the honest labelling, pinned by `test-token-discipline-rule-wired.sh`. The two passes themselves are not gated -- deciding a task IS a rename is judgment, and "pass 1 done" is your prose, so no hook can see either. Not optional; also not checked.

## Pre-Action Echo (ENFORCED)

Before the first Edit, Write, or destructive Bash call: if the task touches more than one file OR more than one tool category (Read, Bash, Edit, Web, Agent), echo the plan in 2-3 bullets and wait for OK. No exceptions for "small" tasks. If you find yourself thinking "this is small, I'll just do it," that is the trigger to echo.

**Scope of (ENFORCED) above: the labelling only, pinned by `test-token-discipline-rule-wired.sh`. The echo itself is structurally unhookable and that is not a TODO.** A PreToolUse hook receives `tool_name` and `tool_input`, never your prose, so "echoed the plan" is invisible to it; and "wait for OK" needs a user turn, which no unattended `claude -p` run has. A blocking branch would deadlock the first Edit of every autonomous run fleet-wide -- the `/q-morning` carve-out was the first sign of that, and the fleet has many more unattended runners now. Still does not apply to `/q-morning` pipeline sub-agents.

<!-- enforcement -->
```json
[
  {
    "clause": "Cleanup / Migration Rule",
    "status": "ADVISORY",
    "note": "token-guard.py is wired and blocking but implements neither grep pass; the rule's own text says the passes are not gated",
    "superseded_by": "was ENFORCED naming q-system/.q-system/token-guard.py, which does not implement this clause",
    "marker_removal_ref": "sp-45473673",
    "directives": 0
  },
  {
    "clause": "Pre-Action Echo",
    "status": "ADVISORY",
    "note": "structurally unhookable: a PreToolUse hook sees tool_input, never prose, and waiting for OK needs a user turn",
    "superseded_by": "was ENFORCED naming q-system/.q-system/scripts/test/test-token-discipline-rule-wired.sh as its receipt; that test pins the LABELLING, not this behaviour",
    "marker_removal_ref": "sp-45473673",
    "directives": 1
  }
]
```
