# Council Debate

Full structured 3-round debate. Positions, challenges, synthesis. 30-90 seconds.

## Execution

### Sub-Agent Guard

Sub-agents cannot spawn other sub-agents. If you are running inside a sub-agent context (the Agent tool is unavailable or errors on use), do NOT attempt parallel agent spawning. Instead, run all 4 personas **sequentially in the current context** for each round. Apply each persona's prompt template yourself, write each take inline, then proceed to the next round. All 3 rounds still execute. Same prompts, same output format, just sequential.

### Step 0: Read Canonical Files

Before spawning any agents, read all relevant files:
- `q-system/my-project/current-state.md`
- `q-system/canonical/discovery.md`
- `q-system/my-project/relationships.md`
- `q-system/canonical/talk-tracks.md`
- `q-system/canonical/objections.md`
- `q-system/my-project/competitive-landscape.md`

Extract relevant content. You'll pass it into agent prompts directly.

### Step 1: Announce

```markdown
## Council Debate: [Topic]

**Personas:** Operator, Buyer, Investor, Contrarian
**Rounds:** 3 (Positions -- Challenges -- Synthesis)
```

### Step 2: Round 1 -- Initial Positions

Launch 4 Agent calls in parallel (single message).

**Each agent prompt:**

```
You are the [PERSONA] on a founder's advisory council.

COUNCIL DEBATE -- ROUND 1: INITIAL POSITIONS

Topic: [The topic]

Your perspective: [PERSONA DESCRIPTION]
Your core question: [CORE QUESTION]

Project data you're grounded in:
---
[RELEVANT CANONICAL FILE CONTENT]
---

Give your initial position from your perspective.
- 50-150 words
- Be specific, reference the project data
- State your key concern or recommendation
- If the data doesn't support a position, say so
- You'll respond to others in Round 2
```

All agents use `model: "sonnet"`.

**Output Round 1:**

```markdown
### Round 1: Initial Positions

**Operator:**
[Position grounded in current-state.md]

**Buyer:**
[Position grounded in discovery.md]

**Investor:**
[Position grounded in talk-tracks.md]

**Contrarian:**
[Position grounded in objections.md]
```

### Step 3: Round 2 -- Challenges

Launch 4 Agent calls in parallel. Each agent receives the full Round 1 transcript.

**Each agent prompt:**

```
You are the [PERSONA] on a founder's advisory council.

COUNCIL DEBATE -- ROUND 2: CHALLENGES

Topic: [The topic]

Here's what the council said in Round 1:
---
[FULL ROUND 1 TRANSCRIPT]
---

Your project data:
---
[RELEVANT CANONICAL FILE CONTENT]
---

Respond to the other personas:
- Reference their specific points ("I disagree with Operator's claim that...")
- Challenge assumptions with evidence from your data
- Build on points you agree with
- 50-150 words
- The value is in genuine friction. Don't be polite about bad ideas.
```

**Output Round 2:**

```markdown
### Round 2: Challenges

**Operator:**
[Response referencing others' points]

**Buyer:**
[Response referencing others' points]

**Investor:**
[Response referencing others' points]

**Contrarian:**
[Response referencing others' points]
```

### Step 4: Round 3 -- Synthesis

Launch 4 Agent calls in parallel. Each agent receives Round 1 + Round 2 transcripts.

**Each agent prompt:**

```
You are the [PERSONA] on a founder's advisory council.

COUNCIL DEBATE -- ROUND 3: SYNTHESIS

Topic: [The topic]

Full debate so far:
---
[ROUND 1 + ROUND 2 TRANSCRIPTS]
---

Your project data:
---
[RELEVANT CANONICAL FILE CONTENT]
---

Final synthesis:
- Where does the council agree?
- Where do you still disagree?
- Your final recommendation given the full discussion
- 50-150 words
- Be honest about remaining disagreements. Forced consensus is worse than acknowledged tension.
```

**Output Round 3:**

```markdown
### Round 3: Synthesis

**Operator:**
[Final synthesis]

**Buyer:**
[Final synthesis]

**Investor:**
[Final synthesis]

**Contrarian:**
[Final synthesis]
```

### Step 5: Council Synthesis

Synthesize the full debate yourself (not an agent). Read all 3 rounds and produce:

```markdown
### Council Synthesis

**Convergence:**
- [Points where 3+ personas agreed]

**Remaining tension:**
- [Points still contested, and why]

**Recommended path:**
[Based on the weight of arguments and canonical data]

**Risk if we proceed:** [What could go wrong]
**Risk if we don't:** [What we lose by waiting]
```

### Step 6: Log Decision

After the founder responds, append to `q-system/canonical/decisions.md` using the format from SKILL.md. Include whether the founder approved, modified, or rejected the recommendation.
