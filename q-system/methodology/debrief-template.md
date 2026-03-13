# Conversation Debrief Template

This template is the **primary workflow** of the Q Founder OS. Use it after every conversation with an investor, customer, design partner, advisor, or potential recruit.

## How to Trigger

Use `/q-debrief [person]` or just paste a conversation transcript (auto-detected).

## Predict-First Step (before founder describes conversation)

After reading the person's history but BEFORE the founder describes what happened, generate predictions:

```markdown
### Pre-debrief predictions (system-generated):
Based on [person]'s profile, history, and current positioning:

**Likely objections surfaced:**
1. [predicted objection from objections.md]
2. [predicted objection]
3. [predicted objection]

**Likely topics discussed:**
1. [predicted topic based on their interests/role]
2. [predicted topic]
3. [predicted topic]

**Predicted relationship outcome:** [warmer / cooler / same] because [reason]
```

After the founder describes the conversation, compare predictions to reality. Log accuracy to `memory/working/predictions.jsonl` with type `debrief_prediction`. Wrong predictions reveal gaps in canonical files.

## The Template

```markdown
## Debrief: [Person] - [Role] - [Company] - [Date]

### What resonated (exact phrases they used):
-

### What confused them:
-

### What they pushed back on:
-

### What they asked that I couldn't answer:
-

### Misclassification risk (did they think we're X?):
-

### Next step agreed:
-

### Changes to canonical positioning (if any):
-

### Proof gaps exposed:
-

### Signal quality check:
- Did they describe a CURRENT pain or agree with a THEORETICAL problem?
- What do they DO TODAY to solve it (even badly)? Tool/process named:
- Did they express willingness to CHANGE their current process?
- Did they identify specific BLOCKERS to trying something new?
- How many minutes before they "got it" without me explaining? (under 2 = hot, 2-5 = warm, 5-10 = lukewarm, 10+ = educating)
- Next step cost: Does the next step cost THEM something (time, access, advocacy) or just me (send deck)?
- Signal level: [Thesis nod / Pain confirmed / Switching intent / Usage commitment]
```

## Signal Quality Routing

After the signal quality check, route the prospect:
- **Thesis nod:** Log insight, do NOT invest more time until they show pain.
- **Pain confirmed:** Priority follow-up. Ask switching friction questions next.
- **Switching intent:** Top priority. Move toward commitment conversation.
- **Usage commitment:** Activate immediately. This is a real partner.

If 3+ conversations land at "thesis nod" with no "pain confirmed," the problem may resonate strategically but not operationally.

## Processing Instructions

After completing the template, route insights to canonical files:

1. **Resonance phrases** -> `canonical/talk-tracks.md` (their exact words, tagged by persona)
2. **Pushback / Objections** -> `canonical/objections.md` (new or updated, with source)
3. **Confusions / Misclassification** -> `canonical/objections.md` (reframing language)
4. **Unanswered questions** -> `canonical/discovery.md` (gap question with context)
5. **Contact context** -> `my-project/relationships.md` (update or create entry)
6. **Graph knowledge base** -> `memory/graph.jsonl` (extract entity-relationship triples: who works where, who introduced whom, what they care about, what objected to, what resonated)
7. **Positioning changes** -> `my-project/current-state.md` (validated or invalidated claims)
7. **Progress log** -> `my-project/progress.md` (log the debrief)
8. **Notion** -> Create Interaction entry (if Notion configured)

## Quality Checklist

- [ ] Every section filled (or marked "N/A")
- [ ] Resonance phrases are verbatim (their words)
- [ ] Objections have a proposed response
- [ ] Next step is concrete (what, when, via what channel)
- [ ] Misclassification risk assessed
- [ ] Signal quality check completed with signal level assigned
- [ ] All canonical routing complete
