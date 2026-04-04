# Reduce Hallucinations -- Anthropic Documentation

Source: https://docs.anthropic.com/en/docs/test-and-evaluate/strengthen-guardrails/reduce-hallucinations
Retrieved: 2026-04-03

## Basic strategies

### 1. Allow Claude to say "I don't know"
Explicitly give Claude permission to admit uncertainty. This simple technique can drastically reduce false information.

Example prompt pattern: "If you're unsure about any aspect or if the report lacks necessary information, say 'I don't have enough information to confidently assess this.'"

### 2. Use direct quotes for factual grounding
For tasks involving long documents (>20k tokens), ask Claude to extract word-for-word quotes first before performing its task. This grounds its responses in the actual text, reducing hallucinations.

Example prompt pattern: "Extract exact quotes that are most relevant. If you can't find relevant quotes, state 'No relevant quotes found.' Only base your analysis on the extracted quotes."

### 3. Verify with citations
Make Claude's response auditable by having it cite quotes and sources for each claim. You can also have Claude verify each claim by finding a supporting quote after it generates a response. If it can't find a quote, it must retract the claim.

Example prompt pattern: "After drafting, review each claim. For each claim, find a direct quote from the documents that supports it. If you can't find a supporting quote for a claim, remove that claim."

## Advanced techniques

### 4. Chain-of-thought verification
Ask Claude to explain its reasoning step-by-step before giving a final answer. This can reveal faulty logic or assumptions.

### 5. Best-of-N verification
Run Claude through the same prompt multiple times and compare the outputs. Inconsistencies across outputs could indicate hallucinations.

### 6. Iterative refinement
Use Claude's outputs as inputs for follow-up prompts, asking it to verify or expand on previous statements. This can catch and correct inconsistencies.

### 7. External knowledge restriction
Explicitly instruct Claude to only use information from provided documents and not its general knowledge.

## Important caveat

While these techniques significantly reduce hallucinations, they don't eliminate them entirely. Always validate critical information, especially for high-stakes decisions.
