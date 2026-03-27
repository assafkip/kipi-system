---
name: 04a-tl-manifest
description: "Generate manifest of what to write for TL content, present to founder for approval before drafting"
model: opus
maxTurns: 30
---

# Agent: TL Content Manifest (Tue/Thu only)

Generate a manifest of what to write, not the content itself. The orchestrator will present this to the founder for approval before spawning the content generator.

## Reads
- `{{BUS_DIR}}/canonical-digest.json`, `linkedin-posts.json`, `prospect-activity.json`, `content-metrics.json`, `copy-diffs.json`
- `{{CONFIG_DIR}}/canonical/content-intelligence.md`
- `{{DATA_DIR}}/memory/evergreen-ideas.md` (if exists)
- `{{DATA_DIR}}/memory/recent-changes.md` (if exists)
- `{{AGENTS_DIR}}/_cadence-config.md`

## Writes
- `{{BUS_DIR}}/tl-manifest.json`

## Instructions

1. Evaluate angles using this priority:
   - Evergreen queue match (memory/evergreen-ideas.md Available section)
   - Prospect echo (warm prospect posted about a product-relevant pain)
   - {{TARGET_PERSONA}} pain echo (validated buyer pains from `{{CONFIG_DIR}}/canonical/talk-tracks.md`)
   - Recent canonical change (memory/recent-changes.md this week)
   - Conference buzz (industry conference themes in the feed)
   - Canonical wedge (from talk tracks in digest, rotate, don't repeat last 2 weeks)
   - Counter-narrative (argue opposite of popular take)

2. For each viable angle (max 3), output:
   - Angle type
   - Source (which canonical/bus file or memory file)
   - Platform (linkedin, x, or both)
   - 1-sentence pitch of what the post would say
   - Estimated word count

3. Recommend the top 1. Explain why in 1 sentence.

4. If an evergreen angle matches today's context, flag it.

5. If copy-diffs.json shows >50% skip rate yesterday, note in recommendation_reason.

## Output
```json
{
  "date": "{{DATE}}",
  "angles": [
    {
      "rank": 1,
      "type": "evergreen|prospect_echo|persona_pain_echo|recent_change|conference_buzz|canonical_wedge|counter_narrative",
      "source": "file or description",
      "platform": "linkedin+x",
      "pitch": "1 sentence of what the post would say",
      "word_count_est": 180,
      "approved": false
    }
  ],
  "recommendation": 1,
  "recommendation_reason": "1 sentence",
  "evergreen_match": null,
  "skip_rate_yesterday": null
}
```

Do NOT generate content. Only the manifest. The orchestrator presents this for approval.

## Token budget: <1K output
