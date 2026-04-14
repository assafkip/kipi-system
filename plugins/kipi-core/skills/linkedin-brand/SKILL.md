---
name: linkedin-brand
description: "LinkedIn + personal brand system for founders. Apply when drafting LinkedIn posts, reactions, DMs, LinkedIn About sections, or planning LLM visibility."
---

# LinkedIn Brand Skill

This skill is the operating system for a founder's LinkedIn presence and broader LLM visibility. It enforces the 2026 algorithm reality (360Brew decoder-only LLM), provides summary frameworks, and governs the cross-platform entity graph that makes a founder legible to ChatGPT, Claude, Gemini, and Perplexity.

## When to Invoke

Auto-fire on any of these:
- Drafting a LinkedIn post, article, or carousel
- Writing a comment, reply, or quote-post reacting to someone else's LinkedIn content
- Drafting a LinkedIn DM
- Writing or editing the LinkedIn About section
- Auditing the founder's LinkedIn profile
- Planning LLM visibility, personal-site schema, or third-party mention pipeline
- Any question containing "LinkedIn," "personal brand," "visibility to LLMs," or "my About section"

Skip for: internal ops chat, code, system files.

## Before Drafting

Always read in this order:
1. `references/playbook.md` — format rules, cadence, first-hour rule
2. `references/voice-check.md` — AI-detection patterns to avoid
3. `references/summary-frameworks.md` — if drafting/editing an About section
4. `references/llm-visibility.md` — if question is about broader visibility

Then read instance-specific files (not bundled in the skill):
- `my-project/linkedin-playbook.md` — this founder's committed pillars
- `my-project/linkedin-summary-template.md` — this founder's current About draft
- `my-project/llm-visibility-plan.md` — this founder's entity graph and mention pipeline

If those instance files do not exist, ask the founder to create them before drafting. Do not invent pillars or positioning.

## Core Rules (ENFORCED on every draft)

### Format
- Zero hashtags, or one high-intent tag max. 3+ tags costs 29% reach.
- External links go in the first comment, never the body. Body links cost 32% reach.
- Short sentences. 8-15 words average. One idea per sentence.
- Scar-anchored. Lead with real experience, not abstract claims.
- Personal-adjacent outperforms pure professional.

### AI-detection patterns (scrub before publishing)
- No em-dashes. Ever.
- No rule-of-three lists ("faster, smarter, better").
- No AI filler: "leverage," "robust," "seamless," "ecosystem," "landscape," "paradigm," "synergy," "utilize," "facilitate," "streamline," "empower," "holistic," "scalable," "next-gen," "disruptive," "excited to share," "in today's landscape."

See `references/voice-check.md` for the full scanner.

### Cadence
- 3 posts per week: Tuesday, Wednesday, Thursday.
- Reposts count as posts.
- 70% time engaging on others' content, 30% posting your own.

### First-hour rule (the actual reach lever)
- Post 3-5 substantive comments each morning on 2nd-degree target posts (not 1st-degree connections). 2nd-degree comments carry 2.6x the weight of your own posts.
- First comment on your own post within 15 min of publishing.
- Revisit your own post at hour 2, hour 6, hour 24 and respond to every comment.

## Reaction-Mode Gate

Before drafting a reaction (comment, reply, quote-post, DM about someone's content):
1. Extract the poster's claims verbatim. No interpretation.
2. Show extracted claims to the founder. Do not draft until confirmed.
3. Draft in founder voice. Reactions are about the poster's ideas, not your product.
4. Self-check: zero product name-drops unless founder explicitly asked.

## Pre-Publish Checklist

Run before returning any draft:

1. Hashtag count: 0 or 1?
2. External links: in first comment only, not body?
3. Zero em-dashes, zero rule-of-three lists, zero AI filler phrases?
4. First sentence scar-anchored? No hedging?
5. Matches one of the founder's committed pillars (from instance file)?
6. Day-of-week = Tue/Wed/Thu?
7. First-hour engagement plan stated (3-5 2nd-degree comments to land)?

If any check fails, fix before returning the draft.

## LLM Visibility Mode

When the question is about visibility beyond LinkedIn (personal site, schema, podcasts, being findable by AI):

1. Read `references/llm-visibility.md` for the entity graph framework.
2. Read instance `my-project/llm-visibility-plan.md` for the founder's committed plan.
3. Apply entity consistency rule: name, title, one-line positioning must be byte-identical across LinkedIn, X, GitHub, personal site, podcast bios.
4. Third-party mentions beat owned content for LLM trust.
5. Skip Forbes/Wikipedia advice unless the founder has ≥5 independent mentions already.

## Output Rules

- Every draft is copy-paste ready. No "[insert hook here]" placeholders.
- Tag drafts with pillar: `[Pillar 1: scar]`, `[Pillar 2: founder-op]`, `[Pillar 3: AI/visibility]`.
- If the founder's pillars aren't in `my-project/linkedin-playbook.md`, ask before drafting.
- Never invent metrics, quotes, or company names the founder didn't provide.
- Mark unverified claims `{{UNVALIDATED}}` or `{{NEEDS_PROOF}}`.

## Related Skills

- `founder-voice` — apply alongside for voice DNA enforcement
- `audhd-executive-function` — apply if founder profile flags AUDHD (all output must be copy-paste actionable)
