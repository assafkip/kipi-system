# Quick Council

Fast single-round perspective check. 4 personas, 1 round, 10-20 seconds.

## Execution

### Sub-Agent Guard

Sub-agents cannot spawn other sub-agents. If you are running inside a sub-agent context (the Agent tool is unavailable or errors on use), do NOT attempt parallel agent spawning. Instead, run all 4 personas **sequentially in the current context**: apply each persona's prompt template yourself, write each take inline, then proceed to the output format in Step 3. Same prompts, same output, just sequential.

### Step 1: Read Canonical Files

Before spawning any agents, read the files each persona needs:
- `q-system/my-project/current-state.md` (Operator)
- `q-system/canonical/discovery.md` + `q-system/my-project/relationships.md` (Buyer)
- `q-system/canonical/talk-tracks.md` (Investor)
- `q-system/canonical/objections.md` + `q-system/my-project/competitive-landscape.md` (Contrarian)

Extract the relevant content. Pass it directly into each agent prompt so they don't need to read files themselves.

### Step 2: Spawn All 4 Personas in Parallel

Launch 4 Agent calls in a single message (parallel execution).

**Each agent prompt follows this template:**

```
You are the [PERSONA NAME] on a founder's advisory council.

QUICK COUNCIL CHECK

Topic: [The topic/decision]

Your perspective: [PERSONA DESCRIPTION]
Your core question: [CORE QUESTION]

Here is the project data you're grounded in:
---
[PASTE RELEVANT CANONICAL FILE CONTENT]
---

Give your take in 30-50 words. Be specific. Reference the project data above.
If the data doesn't cover this topic, say so -- don't guess.
One clear position. No hedging.
```

**Agent configuration:**
- All 4 use `model: "sonnet"` (fast, cheap)
- subagent_type: `general-purpose`

### Step 3: Output

```markdown
## Quick Council: [Topic]

**Operator:**
[30-50 word take grounded in current-state.md]

**Buyer:**
[30-50 word take grounded in discovery.md / relationships.md]

**Investor:**
[30-50 word take grounded in talk-tracks.md]

**Contrarian:**
[30-50 word take grounded in objections.md / competitive-landscape.md]

---

**Consensus:** [Do they agree? On what?]
**Dissent:** [Who disagrees and why?]
**Recommendation:** [Proceed / Reconsider / Needs full debate]
```

### Step 4: Log Decision

If the founder acts on the recommendation, append to `q-system/canonical/decisions.md` using the format from SKILL.md.

## Escalation

If 3+ personas disagree or the topic has significant canonical file implications, recommend:

> This has enough tension for a full debate. Run `council debate: [topic]` for 3 rounds.
