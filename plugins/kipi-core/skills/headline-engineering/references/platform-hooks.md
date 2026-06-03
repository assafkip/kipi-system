# Platform Hooks Reference

The 6 viral patterns + platform-specific char counts + the first-7-words rule.

## The 6 patterns that earn clicks

Sourced from top text-headline posts in r/ChatGPT, r/ClaudeAI, r/OpenAI, r/singularity, r/LocalLLaMA over the last 30 days, plus X 2026 viral hook research (see `research-receipts.md`).

### Pattern A — Absurd concrete object

Take something serious and put it on something absurdly specific.

Examples:
- "I got a real transformer language model running locally on a stock Game Boy Color!" (1,497 upvotes)
- "16x DGX Sparks - What should I run?" (1,591 upvotes)
- "Self-driving motorcycles are being spotted on China's streets without a driver" (2,753 upvotes)
- "1 year of prompts. A 21-byte file fixed it." (used for kipi-system article 1)

Why it works: the specificity creates a "wait, what?" reaction. Generic claims drown; specific objects get clicked.

### Pattern B — Confession + reversal

Personal stake. Public reversal. Past behavior, present pivot.

Examples:
- "I'm done with using local LLMs for coding" (1,028 upvotes)
- "I cannot go back to claude now" (1,214 upvotes)
- "Sam Altman No Longer Believes In Universal Basic Income" (2,864 upvotes)
- "After 6 months of daily AI pair programming, here's what actually works (and what's just hype)" (cross-posted in 3+ subs)

Why it works: implied story arc. The reader wants to know what changed.

### Pattern C — PSA / "admits" exposé

Breaking-news framing for something the company would rather hide.

Examples:
- "Anthropic admits to have made hosted models more stupid" (1,306 upvotes)
- "PSA: Claude Pro no longer lists Claude Code as an included feature" (2,978 upvotes)
- "Permanently banned by OpenAI for 'Cyber Abuse' I didn't commit" (real-user thread)

Why it works: triggers the "wait, did I miss something?" reflex. Implies insider knowledge.

### Pattern D — Specific number + impossible feat

Compound numbers. Payoff line.

Examples:
- "ChatGPT 5.4 Solved a 64-Year-Old Math Problem" (13,108 upvotes)
- "Google's Antigravity 2.0 creates an OS from scratch using 96 agents in 12 hours for under $1K in token costs - and it runs Doom" (1,815 upvotes)
- "I gained 12,847 followers in 63 days" (300% higher engagement than "I grew quickly")

Why it works: specific numbers boost perceived credibility AND clickability. Round numbers (10K, 100M) underperform vs odd specific (12,847, 64-year, 96 agents).

### Pattern E — Naive question

Question in title disarms and pulls clicks. Implied "I don't know either, let's find out."

Examples:
- "Forgive my ignorance but how is a 27B model better than 397B?" (1,167 upvotes)
- "Sitting on 10k in unused openai api credits that will expire, what would you build?" (1,192)
- "Anyone else catch this strange moment on the Figure 03 livestream?" (4,154)

Why it works: lowers ego barrier. Reader feels invited, not lectured.

### Pattern F — "I asked X to..." setup

Setup, then implied payoff.

Examples:
- "I asked ChatGPT to imagine itself in retirement" (17,152 upvotes)
- "I asked ChatGPT for a 'Perfectly Normal Family Picnic', but told it to hide a few subtle details that get more terrifying the longer you look." (1,086 upvotes)

Why it works: reader knows there's a payoff. Title is the setup; image/post is the punchline.

## Platform length ranges

### X (Twitter) 2026
- Tweet limit: 280 chars free, 25K premium
- Optimal engagement: **under 110 chars**
- Sweet spot: **71-100 chars**
- First **5-7 words** decide everything (hook in first line)
- Specific numbers boost CTR 300%
- Replies weighted 27x more than likes — title must provoke, not just inform
- For threads: hook tweet works standalone OR no one reads tweet 2

### Reddit text headlines
- Range: 30-300 chars technical
- Top-performer cluster: **30-66 chars**
- Sweet spot: 30-50 chars for confession/reversal, 45-66 for specific-number patterns
- Subreddit norms matter — r/LocalLLaMA tolerates longer technical specificity; r/ChatGPT rewards punchier emotional shapes

### LinkedIn long-form titles
- Optimal: 60-100 chars
- Hook in first 7 words (same as X)
- Personal story arc baked in works best — "I [time] doing X. Here's what changed."
- Avoid hashtags in title; put them in body

### Medium / Substack titles
- Range: 50-90 chars
- "The X that Y" pattern (declarative + concrete object)
- "Why X" pattern works on Medium specifically (less on Reddit)
- Subtitles are allowed and help — but the main title still has to earn the click

## The first 5-7 words rule

This rule overrides almost everything else.

The first 5-7 words decide:
- Whether anyone reads word 8
- Whether the algorithm shows it to more people (X scores first-line scroll-stop)
- Whether the link gets clicked when shared

Bad: "I spent a year on prompt engineering. A 21-byte file fixed it." (the punch is in word 12)
Good: "1 year of prompts. A 21-byte file fixed it." (year + confession in word 4)

When reviewing a title, cover everything after word 7. Does the hook still work? If not, restructure.

## What's NOT winning

These shapes do not appear in top-performing AI content in 2026:

- "The Ultimate Guide to X"
- "X Things You Need to Know"
- "Why X Matters" (without a number)
- "How to X" (too soft)
- Listicles without confession or scar
- Long colon-separated subtitle titles ("X: A Comprehensive Look at Y")
- AI-style listicle promises ("Top 10 / Best 5 / Essential")

These get clicks ONLY when paired with a strong specific number ("47 things I tested" beats "10 things I tested" because 47 is unusual).

## Cross-references

- [[assaf-voice]] — voice DNA, sentence structure, banned words
- [[linkedin-brand]] — LinkedIn-specific brand and audience rules
- [[founder-voice]] — voice skill propagating across instances
