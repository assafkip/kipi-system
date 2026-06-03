# Research Receipts

Source data behind every claim in `platform-hooks.md` and `headline-templates.md`. So the skill can be challenged, updated, or extended without losing the receipts.

Captured 2026-05-20. If the platform algorithms change materially, this file needs a refresh.

## X (Twitter) optimal length and structure

Source: web research, May 2026, multiple aggregators ([teract.ai](https://www.teract.ai/resources/twitter-algorithm-2026), [tweetarchivist.com](https://www.tweetarchivist.com/how-to-write-viral-tweets-2025), [hashmeta.com](https://hashmeta.com/blog/twitter-thread-marketing-the-complete-guide-to-creating-viral-threads-that-drive-engagement/), [shippost.lol](https://shippost.lol/blog/x-twitter-for-developers/)).

Key claims:
- Tweets under 110 chars perform best
- Sweet spot 71-100 chars
- Longer tweets (240-259 chars) also see a secondary engagement peak
- Hook in first 5-7 words decides scroll-stop
- Specific numbers boost CTR ~300% (the "12,847 followers in 63 days" beats "I grew quickly" pattern)
- Replies weighted 27x more than likes in 2026 algorithm

Caveat: these stats come from social-media-marketing aggregators with skin in the game. The character-count and first-7-words observations match observed engagement on top-performing real tweets. Treat as directional, not gospel.

## Reddit top text headlines (last 30 days, AI subs)

Source: direct Reddit MCP pulls on 2026-05-20, top-of-month sorted across r/ChatGPT, r/ClaudeAI, r/OpenAI, r/singularity, r/LocalLLaMA, r/ArtificialIntelligence.

Top text-driven headlines and their lengths:

| Headline | Sub | Upvotes | Chars |
|----------|-----|---------|-------|
| Chat GPT got that guy in trouble and he doesn't even know it yet…lol | r/ChatGPT | 22,810 | 66 |
| ChatGPT 5.4 Solved a 64-Year-Old Math Problem | r/ChatGPT | 13,108 | 45 |
| Can't believe that ChatGPT has such in-depth medical knowledge | r/ChatGPT | 8,943 | 60 |
| Karpathy joins Anthropic | r/ClaudeAI | 5,869 | 24 |
| PSA: Claude Pro no longer lists Claude Code as an included feature | r/ClaudeAI | 2,978 | 66 |
| I cannot go back to claude now | r/OpenAI | 1,214 | 30 |
| I'm done with using local LLMs for coding | r/LocalLLaMA | 1,028 | 41 |
| Anthropic admits to have made hosted models more stupid | r/LocalLLaMA | 1,306 | 54 |
| Anthropic to reach 100% global GDP in 21 months | r/singularity | 2,484 | 48 |
| Sam Altman No Longer Believes In Universal Basic Income | r/singularity | 2,864 | 55 |
| Self-driving motorcycles are being spotted on China's streets without a driver | r/singularity | 2,753 | 78 |
| Forgive my ignorance but how is a 27B model better than 397B? | r/LocalLLaMA | 1,167 | 60 |
| I asked ChatGPT to imagine itself in retirement | r/ChatGPT | 17,152 | 47 |

Observed pattern: top-performer cluster lands at 30-66 chars. Outliers up to ~78 chars still hit when the specific noun ("self-driving motorcycles", "Karpathy") carries the click.

## The 6 viral patterns (named from observation)

Distilled by cross-pattern analysis of the table above and ~150 more posts pulled in the same session:

- Pattern A: absurd concrete object
- Pattern B: confession + reversal
- Pattern C: PSA / "admits" exposé
- Pattern D: specific number + impossible feat
- Pattern E: naive question
- Pattern F: "I asked X to..." setup

Each pattern has at least 3 top-100 examples in the dataset. The patterns are observation-derived, not theoretical.

## What's NOT in the top dataset (negative data)

In 150+ pulled posts, ZERO instances of:
- "The Ultimate Guide to X"
- Generic "Why X Matters" titles (without numbers)
- "Top 10 / Best 5 / Essential" listicles (the only listicle that landed used an unusual number — "11 Claude things")
- "Mastering X" / "Unlocking Y"
- Em-dash subtitle formats
- "In Today's Fast-Paced World..."

Conclusion: AI-style content-marketing title shapes do not earn clicks in AI-savvy subreddits in 2026. These shapes are filtered by audience pattern recognition.

## Length ranges by platform (derived)

| Platform | Min | Sweet | Max | Source |
|----------|-----|-------|-----|--------|
| X | 30 | 71-100 | 110 | aggregator research |
| Reddit text | 30 | 30-66 | ~80 | direct top-of-month data |
| LinkedIn long-form | 50 | 60-100 | 150 | community guidance, less direct data |
| Medium | 40 | 50-90 | 100 | community guidance |
| Substack | 40 | 60-90 | 110 | community guidance |

LinkedIn and Medium ranges are softer than X and Reddit because there's less verified click-through data at the title level. The Reddit/X numbers should be trusted more.

## Counter-evidence and limitations

- Reddit headline data is from a single 30-day window. Headlines that go viral in one window may not transfer to another (election cycle, model releases, scandals shift the language).
- The "top of month" sort favors content with sustained engagement. Doesn't capture the high-spike, fast-decay viral that died in 24 hours.
- I did not check Substack notes or Threads. The dataset is X + Reddit + secondary LinkedIn/Medium signals.
- Many top posts are image-driven; their text titles ride along with the image. Pure text titles in the dataset are about 35% of the top posts.

## Update protocol

When this file gets stale (algorithm changes, new platforms, voice corrections):

1. Re-pull top posts from the 6 source subreddits via Reddit MCP, time_filter=month.
2. Re-run the character-count distribution and cluster analysis.
3. Validate the 6 patterns still hold; add new patterns if observed.
4. Update the headline-templates.md examples with current top performers.
5. Bump the "Captured" date at the top of this file.

Trigger to refresh: any time the voice-lint or headline-lint hooks start producing false positives that map to platform shifts, or every ~90 days.
