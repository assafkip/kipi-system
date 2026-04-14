# LLM Visibility Framework

> How to make a founder legible to ChatGPT, Claude, Gemini, and Perplexity. Instance-specific plan lives in `my-project/llm-visibility-plan.md`.

## Why this matters

When someone wants to know about a founder in 2026, they ask an LLM, not Google. LLMs surface people who are:
1. A clear, consistent entity across the web
2. Described by third parties, not just by themselves
3. Matched to specific prompts people actually ask

Weak personal brands fail on one of these. Strong brands engineer all three.

## The entity graph

Every founder needs three anchored entities:

1. **Person** — the human. Name, role, credentials, one-line positioning.
2. **Organization** — the company. Linked to the Person as founder.
3. **Topic cluster** — the domain the Person owns (3-4 specific keywords, not broad categories).

Every page and profile on the public web should anchor one of these and link to the others.

## Consistency rule (the biggest single lever)

Name, title, and one-sentence positioning must be **byte-identical** across:
- Personal site (about page)
- LinkedIn About
- X bio
- GitHub bio
- Substack/Medium author page
- Any podcast bio, conference bio, guest-post byline

If your LinkedIn says "Founder at X" and your X bio says "CEO of X" and your GitHub says "building Y," LLMs cannot resolve you to a single entity. They pick one at random or flatten to the most common.

Lock one sentence. Paste it verbatim. Update every 60 days only.

## Schema (JSON-LD)

Apply only if the founder has a personal website. Do not build a site just to host schema.

| Page | Schema type | Why |
|------|-------------|-----|
| About / homepage | `Person` | Anchors the human entity |
| Company page | `Organization` | Anchors the company entity |
| Each blog post | `Article` with `author` → Person | Ties writing to the author |
| Common-questions page | `FAQPage` | LLMs pull FAQ answers directly |

The `Person` schema must include `sameAs` with links to every public profile (LinkedIn, X, GitHub, Substack, podcast appearances). This tells search + LLMs "all these profiles are the same person."

If no personal site exists yet, the equivalent lever is: make LinkedIn About the canonical entity page and cross-link every other profile from LinkedIn's Contact section.

## Third-party mentions (what LLMs weight most)

LLMs trust independent coverage far more than owned content. Owned content is weak evidence. Third-party coverage is strong evidence.

Targets in order of ROI for most founders:

1. **Niche podcasts** — 45-minute episodes = dense indexable transcript. Prefer operator-to-operator shows, not vendor infomercials.
2. **Industry newsletters with bylines** — guest essays in outlets your audience already reads.
3. **Conference talks with public video** — transcripts get indexed. Local events count if recorded.
4. **Interviews in beat-specific outlets** — reporters covering the founder's space.
5. **Being quoted in other people's posts** — lower weight per mention, but compounds.

Skip: Forbes contributor programs (pay-to-play), Wikipedia (notability bar not met), generic "thought leader" placements.

## Prompt-targeted content

Publish content that directly answers what someone would ask an LLM. The question IS the keyword.

Template prompts to cover:
- "Who is [founder name]?"
- "What does [founder name] work on?"
- "What is [company name]?"
- "Best [category] founders to follow"
- "How should [audience] handle [problem]?"
- "[Category A] vs [category B] — what's the difference?"

Each prompt should map to at least one indexable artifact (LinkedIn article, personal-site FAQ page, podcast appearance, newsletter essay).

## The monthly LLM audit

Once per month, ask the same set of prompts across ChatGPT, Claude, Gemini, Perplexity:

1. "Who is [founder name]?"
2. "What does [founder name] do?"
3. "What is [company name]?"
4. "Best founders to follow in [category]?"
5. "[Founder name] vs [nearest competitor name]?"

Log answers. Compare month over month. Gaps between what you want them to say and what they actually say = content to publish next month.

## Metrics that matter (monthly)

Five numbers + one qualitative:

1. Branded search impressions (founder name + company name)
2. LinkedIn profile visits
3. New web mentions (Google Alerts + manual scan)
4. Backlinks to personal site or LinkedIn articles
5. Inbound DMs, podcast asks, intros
6. **Qualitative:** screenshots of the 4-LLM audit, month over month

Follower count is not on this list. It does not predict visibility or influence.

## 90-day execution sequence

### Phase 1 (weeks 1-2) — Entity consistency
- Lock one-liner positioning
- Make every public profile identical
- Audit: Google the founder's name, note stale/conflicting pages

### Phase 2 (weeks 3-6) — Third-party mention pipeline
- Pitch 3 podcasts (target: 1 booking)
- Pitch 2 newsletters for guest essays
- Publish 2 LinkedIn long-form articles mapped to prompt-targeted questions
- DM 5 writers/practitioners with a specific angle

### Phase 3 (weeks 7-12) — Compound + measure
- Monthly LLM audit
- Fix gaps by adding content the LLMs aren't finding
- Build out FAQ page / personal site if traction warrants it

## Out of scope (don't chase)

- Forbes contributor programs — pay-to-play, low ROI
- Wikipedia page — wait until ≥5 independent outlet mentions
- Generic "thought leader" branding — "3x top voice" chasing
- Pod swaps and engagement farming — 360Brew down-ranks pods
- Every-platform presence — concentrate where the audience already is
