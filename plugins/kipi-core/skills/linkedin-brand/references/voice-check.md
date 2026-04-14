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

## Banned phrases (AI filler)

Scrub every instance. If the sentence still makes sense without it, delete. If not, rewrite.

- leverage
- robust
- seamless
- seamlessly
- ecosystem
- landscape
- paradigm
- synergy
- utilize (use "use")
- facilitate
- streamline
- empower
- holistic
- scalable
- next-gen
- disruptive
- cutting-edge
- game-changing
- innovative
- thrilled
- excited to share
- in today's landscape
- in today's world
- in an increasingly
- delve
- at the intersection of
- dive deep
- deep dive
- unlock
- unleash
- transform (unless literal)
- revolutionize
- harness
- drive (as in "drive outcomes")

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

## Banned phrases (founder-voice specific)

Per founder-voice skill:
- "I think" / "I believe" / "it seems like" / "arguably" / "perhaps"
- Replace with direct statement, or say "I don't know yet."

## Hedging patterns to catch

- "might be worth considering"
- "potentially useful"
- "could help with"
- "may be able to"
- "tends to"

Rewrite as direct claims.

## Sentence-length scanner

If any sentence exceeds 25 words, break it. If the paragraph exceeds 3 sentences, split it. White space is a feature.

## Voice: first-person openers

Per voice and AUDHD rules: DMs, emails, and comments start with "I," never the recipient's name.

```
BAD:  Hey Sarah, loved your post about...
GOOD: I read your post on [topic] three times.
```

## Scoring

When reviewing a draft, return one of:
- **PASS** — no hits. Ready to publish.
- **FIX** — one or more hits. List each with line reference and a proposed rewrite.
- **REWRITE** — sounds like AI even without explicit banned terms. Start over with scar-anchored opener.
