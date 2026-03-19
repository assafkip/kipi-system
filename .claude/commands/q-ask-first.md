Draft targeted questions for the founder before burning tokens on research.

## Why this exists

The founder often knows the answer to questions that would take 50+ tool calls to research. This command forces a structured pause to identify collection gaps and draft questions.

## Instructions

1. Read current state from:
   - `q-system/my-project/current-state.md`
   - `q-system/my-project/relationships.md`
   - `q-system/canonical/discovery.md`
   - Any active investigation or research context in `q-system/memory/working/`

2. Identify the **top 3-5 collection gaps** - things you don't know that would significantly change your next actions. Prioritize:
   - Relationships between people (who knows whom, who introduced whom)
   - Internal context the founder has but hasn't shared (org charts, budget cycles, decision timelines)
   - Identification of unknown persons or companies mentioned in conversations
   - Validation of assumptions you're currently treating as facts

3. For each gap, draft a **targeted question**:
   - Be specific. "Do you know X?" not "Tell me about your network."
   - Explain WHY you need it: "This would save me from researching Y"
   - One question per gap. No compound questions.

4. Format as a **copy-paste-ready message** the founder can send (to a client, advisor, or team member) or answer directly.

5. Present to the founder for review. Never send directly.

## Output format

```
## Questions Before I Continue

I have [N] gaps that you might be able to answer faster than I can research:

1. **[Question]**
   Why: [What this unblocks and what research it saves]

2. **[Question]**
   Why: [What this unblocks and what research it saves]

...

If you can answer any of these, it saves significant research time.
If not, I'll proceed with [fallback approach].
```
