# Article Flow — 2026-05-21

Record of how article 1 ("1 year of prompts. A 21-byte file fixed it.") got built. Captured as repeatable methodology for future article work.

## The flow that worked

1. **Research first.** Pulled Reddit (r/ChatGPT, r/ClaudeAI, r/OpenAI, r/singularity, r/LocalLLaMA, r/ChatGPTPro, r/productivity), plus WebSearch on AI fatigue and enterprise rollout failure data. Perplexity was 401 on first try; founder ran it manually with a vendor-blocker prompt.
2. **Vendor audit.** Killed v1 of the brief because it was anchored on HCLTech / McKinsey / Temporal stats. Rebuilt v2 with Reddit + peer-reviewed + Pew + SHRM + Stack Overflow Developer Survey as primary anchors. Vendor stats demoted to strawmen only.
3. **Cross-instance reality check.** Spawned four parallel agents to map the actual running systems at kipi-system, KTLYST strategy, Pure Spectrum, 4 Points Consulting. Discovered the killer fact: the 21-byte `.active-case` file orchestrating 24 commands at 4 Points. Same skeleton, four topologies. This became the article spine.
4. **Headline research.** Pulled top text-driven Reddit posts from last 30 days across 6 AI subs. Distilled 6 viral patterns (absurd object, confession + reversal, PSA / admits, specific number + feat, naive question, "I asked X to..."). Char count sweet spots: X 71-100, Reddit 30-66, LinkedIn 60-100, Medium 50-90.
5. **Voice skill loaded.** Pulled full assaf-voice writing-samples + voice-dna + gotchas before drafting.
6. **First draft.** ~1,250 words. Founder caught seven voice misses in one read: percentages from Stack Overflow stat, slash-command references, rule-of-three patterns, "I almost cried" too vulnerable, "four businesses" too loud, "fixed it" too marketing.
7. **Hook architecture decision.** Founder asked "shouldn't this be a hook?" Yes. Skills are aspirations. Built voice-lint v1.
8. **Hook caught more than the founder eyeballed.** v1 found 13 rule-of-three violations the founder counted as 7 manually. Code beat eyeballing. The whole article's point.
9. **Hook had blind spots.** Founder caught comma-triplets within a sentence and cross-paragraph fragment chains. Built voice-lint v2 with new detectors. Plus batch-uniformity-lint, format-lint, audhd-lint, headline-lint, decision-origin-tag-lint.
10. **Article cut from 1100 to 418 words.** Founder pushed back: "you are explaining way too much HOW. I got bored in the middle." Cut every tutorial section. Kept confession, reveal, inversion, contrast, sharp close.

## The methodology in one line

Research with vendor blockers → cross-instance reality check → voice skill + hooks → iterate against the hook output, not just self-audit.

## Voice mistakes to never repeat

- Statistical citations from Stack Overflow / Pew / industry surveys as anchor evidence in published founder content
- Backticked slash-command references in prose (`/q-foo` style)
- Three consecutive sentences with the same first word
- Three short single-noun-sentence paragraphs in a row
- Three comma-separated parallel phrases inside a single sentence
- Three single-sentence paragraphs in a row even when starting words differ
- "Fixed it" / "transformed" / "unlocked" marketing-y verbs in headlines
- Over-explaining HOW (turns the article into a tutorial)
- Loud opener that flexes scale ("I run four different businesses on one shared AI system" as the lead)

## Headline candidates considered

- The 21-byte file that runs my consulting practice. (50 chars, kept early then dropped)
- 1 year of prompts. A 21-byte file fixed it. (44 chars, current — but founder flagged "fixed it" as too marketing)
- I had AI memory backwards for a year. (38 chars, witness confession)
- The filesystem is the brain. AI is the interpreter. (52 chars, direct lift of central inversion)
- Twenty-four skills resolving against one 21-byte file. (55 chars, specific receipt)
- Your AI memory lives in a filesystem, not a context window. (60 chars, declarative thesis)

Pending: pick the final headline before publishing.

## Nano Banana cover image prompts

### Primary (matches the headline's inversion framing)

```
A close-up photograph of a hand-drawn diagram on lined notebook paper, shot under warm desk-lamp light. The diagram shows two labeled boxes connected by arrows. The left box is large and labeled "BRAIN" with the word crossed out in red pen, and "AI" written underneath in small handwriting. The right box is small and labeled "BACKUP" with the word crossed out in red pen, and "filesystem" written underneath in red marker. Above the diagram, in block caps with a red marker: "I HAD THIS BACKWARDS." A faint coffee cup ring stains the lower-right corner. Slight paper texture, 35mm grain. Mood: late-night revelation, hand-drawn proof of an inverted mental model. Aspect ratio 16:9. No text overlays beyond what is in the diagram itself.
```

### Alternative (artifact-focused)

```
A photograph, slight overhead angle. A black mechanical keyboard fills most of the frame. Centered on the spacebar, a single small white index card sits flat. The card has ".active-case" typed in monospace on the top line and "case-014-trump-coin" on the line below. A desk lamp casts amber light from the upper-right corner. Slight texture on the keys, slight grain on the card. The composition makes the small card feel like it is running the whole machine. Aspect ratio 16:9.
```

## Hooks built this session

| Hook | Pairs with | Scope |
|------|-----------|-------|
| voice-lint.py v2 | assaf-voice, founder-voice | published content paths |
| linkedin-format-lint.py | linkedin-brand | LinkedIn output paths |
| headline-lint.py | headline-engineering | files with H1 in published paths |
| batch-uniformity-lint.py | assaf-voice batch rule | files with 3+ post/comment blocks |
| format-lint.py | assaf-voice DM/email rules | email/dm output paths |
| audhd-lint.py | audhd-executive-function | schedule HTML + morning-log JSON |
| decision-origin-tag-lint.py | sycophancy.md | canonical/decisions.md |

All wired in `.claude/settings.json` PostToolUse Edit|Write.

## settings.json snippet for sibling instances

Each kipi instance has its own `.claude/settings.json`. To wire the new hooks, add these entries to the `hooks.PostToolUse[0].hooks` array (alongside existing wiring-check):

```json
{
  "type": "command",
  "command": "python3 \"$CLAUDE_PROJECT_DIR/q-system/.q-system/scripts/voice-lint.py\"",
  "timeout": 5
},
{
  "type": "command",
  "command": "python3 \"$CLAUDE_PROJECT_DIR/q-system/.q-system/scripts/linkedin-format-lint.py\"",
  "timeout": 5
},
{
  "type": "command",
  "command": "python3 \"$CLAUDE_PROJECT_DIR/q-system/.q-system/scripts/headline-lint.py\"",
  "timeout": 5
},
{
  "type": "command",
  "command": "python3 \"$CLAUDE_PROJECT_DIR/q-system/.q-system/scripts/batch-uniformity-lint.py\"",
  "timeout": 5
},
{
  "type": "command",
  "command": "python3 \"$CLAUDE_PROJECT_DIR/q-system/.q-system/scripts/format-lint.py\"",
  "timeout": 5
},
{
  "type": "command",
  "command": "python3 \"$CLAUDE_PROJECT_DIR/q-system/.q-system/scripts/audhd-lint.py\"",
  "timeout": 5
},
{
  "type": "command",
  "command": "python3 \"$CLAUDE_PROJECT_DIR/q-system/.q-system/scripts/decision-origin-tag-lint.py\"",
  "timeout": 5
}
```
