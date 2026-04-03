---
name: council
description: "Multi-persona debate for founder decisions. 4 personas argue a topic across structured rounds."
---

# Council

Multi-agent debate for founder decisions. 4 personas argue a topic across structured rounds, respond to each other's actual points, then synthesize. Produces a visible transcript and a recommended path.

## When to Use

Invoke when:
- Conflicting signals from conversations and you need to decide which to follow
- About to change positioning in canonical files (`/q-calibrate`)
- Design partner asks for something that might pull you off-wedge
- Investor feedback contradicts buyer feedback
- Competitive move detected and you need a response strategy
- Any decision where "it depends" means you need structured tension
- User says "council", "debate this", "weigh options", "get perspectives"

## Workflow Routing

| Trigger | Workflow | Time |
|---------|----------|------|
| Full structured debate (3 rounds) | `workflows/debate.md` | 30-90 sec |
| Quick sanity check (1 round) | `workflows/quick.md` | 10-20 sec |

**Default to Quick.** Use Debate only for positioning changes, pre-investor prep, or decisions that affect canonical files.

## The Personas

4 personas, each anchored to real project files. They read the files before speaking -- grounded opinions, not generic advice.

| Persona | Perspective | Reads | Core Question |
|---------|------------|-------|---------------|
| **Operator** | What we can actually do today | `q-system/my-project/current-state.md` | "Can we ship this with what we have?" |
| **Buyer** | What a CISO/security leader would pay for | `q-system/canonical/discovery.md`, `q-system/my-project/relationships.md` | "Would a buyer pay for this? Does it match what they asked for?" |
| **Investor** | The fundable narrative | `q-system/canonical/talk-tracks.md` | "Does this sharpen or dilute the story?" |
| **Contrarian** | What's wrong, what we're not seeing | `q-system/canonical/objections.md`, `q-system/my-project/competitive-landscape.md` | "What breaks? What are we ignoring?" |

### Persona Rules

- Every persona speaks from their anchored files, not from general knowledge
- If a canonical file is empty/template, the persona says "I don't have data to ground this" -- no guessing
- Personas reference specific entries from their files when making points
- Contrarian must raise at least one uncomfortable point per round

## Output

Every council session produces:
1. **Visible transcript** -- the full debate, readable
2. **Recommended path** -- synthesized from convergence
3. **Decision log entry** -- appended to `q-system/canonical/decisions.md` with `[COUNCIL-DEBATED]` origin tag

### Decision Log Format

```markdown
### [Decision summary]
- **Date:** YYYY-MM-DD
- **Origin:** [COUNCIL-DEBATED]
- **Mode:** Quick / Debate
- **Trigger:** [What prompted this]
- **Convergence:** [Where personas agreed]
- **Dissent:** [Where they disagreed]
- **Decision:** [What the founder chose]
- **Founder action:** [APPROVED / MODIFIED / REJECTED] the recommendation
```

The founder always makes the final call. Council recommends, founder decides.

## Integration with Q System

| Q Command | Council Role |
|-----------|-------------|
| `/q-calibrate` | Quick check before any canonical file change |
| `/q-debrief` with conflicting signals | Quick check: "signal or noise?" |
| `/q-plan` with competing priorities | Debate: which path to take |
| Pre-investor meeting | Debate: stress-test the narrative |
| Design partner feature request | Quick check: "build / park / counter-offer" |

## Token Budget

- Quick: ~20K tokens (4 agents x 1 round). Fine for daily use.
- Debate: ~60K tokens (4 agents x 3 rounds). Use for real decisions only.

Before running a Debate, ask: "Is this decision worth 60K tokens?" If the answer is "probably not," use Quick.
