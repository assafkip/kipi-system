# Voice Check (AI-detection scanner)

> Scan every draft against this list before returning. Any match = rewrite, not flag.

## Hard-banned tokens

### Em-dashes
Every em-dash gets replaced. No exceptions. AI-detection signal.

Replace with: period, comma, colon, or sentence break.

```
BAD:  I spent a decade chasing threat actors — and watched the same bug ship four times.
GOOD: I spent a decade chasing threat actors. The same bug shipped four times.
```

### Rule-of-three lists
Any "X, Y, and Z" triplet where each item is a single adjective or short phrase. AI-detection signal.

```
BAD:  faster, smarter, and more reliable
BAD:  detection, response, and recovery
GOOD: faster. And more reliable when it matters.
GOOD: detection and response. Recovery is someone else's job.
```

Exceptions: if all three items are concrete nouns with real specificity (company names, product names, numbers), the triplet is fine.

```
OK: LinkedIn, Google, Meta (specific companies, not abstract qualities)
```

## Banned words and phrases (AI filler)

Owned by `plugins/kipi-core/kipi-mcp/src/kipi_mcp/draft_scanner.py` and applied by
`kipi_voice_lint`. This file does not duplicate them.

The copy that used to sit here had drifted: `facilitate`, `harness`, `drive`,
`unleash` and `I think` were listed as banned and are in no enforcer (measured
2026-09-02, zero hits each). Scrubbing a word the linter does not ban is wasted
work; trusting this file to be complete is worse. Run the linter.

## Banned phrases (LinkedIn-specific cringe)

- "Thoughts?"
- "Agree or disagree?"
- "Drop a fire emoji if..."
- "Comment below if you..."
- "Follow for more"
- "Tag someone who..."
- "Let me know in the comments"
- "Who else has..."
- "Hot take:"

## Hedged assertions (judgment, not linted)

No enforcer bans these; the linter only reports hedging DENSITY as a metric.
- "I think" / "I believe" / "it seems like" / "arguably" / "perhaps"
- Replace with a direct statement, or say "I don't know yet."

## Hedging patterns to catch

- "might be worth considering"
- "potentially useful"
- "could help with"
- "may be able to"
- "tends to"

Rewrite as direct claims.

## Sentence-length scanner

If any sentence exceeds 25 words, break it. If the paragraph exceeds 3 sentences, split it. White space is a feature.

## What this file is for

Judgment-only checks. The linter cannot see any of these:

- Does the opener anchor in a real experience, or just sound like it does?
- Does it read as one specific person, or as anyone in the category?
- Is any triplet an abstract-quality list rather than concrete nouns?

A draft that passes `kipi_voice_lint` can still fail all three.