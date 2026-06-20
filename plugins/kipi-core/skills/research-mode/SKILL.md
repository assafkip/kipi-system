---
name: research-mode
description: Anti-hallucination research mode. Toggle on to enforce citation requirements, source grounding, and "I don't know" behavior. Toggle off for creative work.
---

# Research Mode

Activates anti-hallucination constraints based on Anthropic's documentation. Stay in this mode until the user says to exit.

Source: [Anthropic - Reduce Hallucinations](https://docs.anthropic.com/en/docs/test-and-evaluate/strengthen-guardrails/reduce-hallucinations)

**Before starting:** Read `references/anthropic-reduce-hallucinations.md` for the full technique set from Anthropic's documentation. The constraints below are derived from that source.

## Constraints (ALL active simultaneously)

### 1. Say "I don't know"
If you don't have a credible source for a claim, say so. Don't guess. Don't infer. "I don't have data on this" is always a valid answer.

### 2. Verify with citations
Every recommendation, claim, or piece of advice must cite a specific source:
- A file in the current project
- An external source found via web search (with URL)
- A named expert, paper, or researcher
- Official documentation

If you generate a claim and cannot find a supporting source, retract it. Do not present it.

### 3. Direct quotes for factual grounding
When working from documents, extract the actual text first before analyzing. Ground your response in word-for-word quotes, not paraphrased summaries. Reference the quote when making your point.

## Source lookup order (ENFORCED -- follow this cascade)

Check sources in this order. Stop at the first level that answers the question.

**Level 1 -- Local files (zero cost):**
Use Grep and Read to search the current project. Canonical files, docs, code, and config are the cheapest, most reliable sources. If the claim is about this project, local files ARE the citation.

**Level 2 -- Perplexity (low cost, preferred for all web research):**
Call `mcp__perplexity__perplexity_ask` with a focused question. Perplexity returns a grounded answer with inline citations in a single call. Cite the Perplexity response and its source URLs verbatim. Do NOT paraphrase without attribution.

- Use `sonar` for general questions, `sonar-pro` for technical depth or multi-source synthesis.
- Ask one question per call. Do not stuff multiple topics into one prompt.
- If Perplexity returns "I don't know" or no citations, treat it as no answer. Escalate to Level 3 only if the founder explicitly asks for direct source text.

**Level 3 -- WebFetch for direct quotes (rare, high cost):**
Only when Perplexity's summary is insufficient and you need word-for-word text from a specific page. Use sparingly.

**Level 4 -- Scholar Gateway (for academic claims):**
For academic papers or research findings, use Scholar Gateway MCP if available. Structured results, no page scraping.

**Level 5 -- Firecrawl scrape-to-FILE (persist full source; for large or long-lived research projects):**
When you need the FULL text of many pages SAVED for later search and citation (not summarized into context), run `q-system/.q-system/scripts/firecrawl-scrape.py <url> <output-dir>`. It writes the page's full markdown (`onlyMainContent`) to a file, so the cascade can grep + cite thousands of sources without hitting context limits. Requires `FIRECRAWL_API_KEY` (env var ONLY; no committed secret). Fail-closed on an empty body (persists nothing). Use only when persistence beats a one-shot Perplexity/WebFetch answer.

### Token budget
- Maximum 3 Perplexity calls per research question
- Maximum 2 WebFetch calls per research question (only if Level 2 was insufficient)
- WebSearch is deprecated in this skill. Use Perplexity instead.
- If you hit the limit: summarize what you found, list what remains unverified, and ask the user if they want to go deeper
- Parallel calls are fine. Serial retry loops are not.

### What counts as "cited"
- Local file path + line number = cited
- Perplexity answer + source URLs it returned = cited
- Named paper/author + year = cited (mark `{{VERIFY_URL}}` if no link)
- "I recall from training data" = NOT cited. Say "I believe X but cannot cite a specific source."

## What this mode is NOT
- It is NOT the default. Creative thinking, brainstorming, and novel ideas don't require this mode.
- It does NOT mean "be slow." Research efficiently. Use tools in parallel.
- It does NOT mean "only use existing ideas." You can synthesize across sources to reach new conclusions, but the inputs must be grounded.

## How to exit
Say "exit research mode" or switch to any other task.

## Relationship to the broader anti-hallucination architecture

Research mode is the runtime enforcement layer. It applies the cite-or-retract rule and the source-lookup cascade during a single session.

The broader pattern is documented at `q-system/methodology/anti-hallucination.md`. That doc covers:
- The thesis (LLM is unreliable, make mistakes findable)
- The full loop (pre-hooks, structured output, post-hooks, verifier, audit, canonical update)
- Source-of-truth hierarchy (graph.jsonl beats canonical beats dashboard beats drafts)
- What's automated vs structural vs manual
- Worked example of catching a real contradiction

Use research mode when you need runtime enforcement. Read the methodology doc when you need to understand why this skill exists and how it fits the rest of the system.
